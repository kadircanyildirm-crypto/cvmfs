#!/usr/bin/env python3
"""Summarise compiler warnings from a build log.

Counts each (file, line, category) once no matter how many translation units
report it, and separates CVMFS's own sources from vendored third-party code.

Usage:
  git ls-files > tracked.txt
  warning_report.py build.log --root . --build build --tracked tracked.txt
"""
import argparse
import posixpath
import re
import sys
from collections import Counter

# gcc and clang both emit "path:line:col: warning: text [-Wcategory]"; the
# column and the category are optional.
WARNING = re.compile(
    r"^(?P<path>[^\s:][^:]*):(?P<line>\d+):(?:\d+:)? warning: "
    r"(?P<text>.*?)(?: \[(?P<cat>-W[\w=+-]+)\])?$"
)

# Some log collectors prefix every line with an ISO-8601 timestamp.
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z ")


def normalise(path, root, build):
    """Return the path relative to root, or None if it falls outside."""
    path = path.replace("\\", "/")
    if not posixpath.isabs(path):
        # ninja and make report paths relative to the build directory
        path = posixpath.join(build, path)
    path = posixpath.normpath(path)
    if not path.startswith(root + "/"):
        return None
    return path[len(root) + 1:]


def collect(lines, root, build, tracked=None):
    """Split the warnings into CVMFS's own sources and everything else.

    Given a set of tracked files (git ls-files) the split is exact.  Without
    one it falls back to "anything under the build directory is vendored",
    which misfiles the third-party sources that land outside of it.
    """
    own, other = {}, {}
    build_rel = normalise(posixpath.join(build, "x"), root, build)
    build_rel = posixpath.dirname(build_rel) if build_rel else ""

    for raw in lines:
        line = TIMESTAMP.sub("", raw.rstrip("\n").rstrip("\r"))
        match = WARNING.match(line)
        if not match:
            continue
        relative = normalise(match.group("path"), root, build)
        if relative is None:
            continue
        key = (relative, int(match.group("line")),
               match.group("cat") or "(uncategorised)")
        if tracked is not None:
            is_own = relative in tracked
        else:
            is_own = not (build_rel and relative.startswith(build_rel + "/"))
        (own if is_own else other).setdefault(key, match.group("text"))
    return own, other


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("--root", default=".", help="source tree root")
    parser.add_argument("--build", default="build", help="build directory")
    parser.add_argument("--out", default="warnings.tsv")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--tracked",
                        help="file holding the output of `git ls-files`; only "
                             "those paths count as CVMFS sources")
    args = parser.parse_args(argv)

    root = posixpath.normpath(args.root.replace("\\", "/")).rstrip("/")
    build = args.build.replace("\\", "/")
    if not posixpath.isabs(build):
        build = posixpath.join(root, build)
    build = posixpath.normpath(build)

    tracked = None
    if args.tracked:
        with open(args.tracked) as handle:
            tracked = set(line.strip() for line in handle if line.strip())

    with open(args.log, errors="replace") as handle:
        own, other = collect(handle, root, build, tracked)

    with open(args.out, "w") as out:
        out.write("scope\tfile\tline\tcategory\ttext\n")
        for scope, table in (("cvmfs", own), ("thirdparty", other)):
            for key in sorted(table):
                out.write("%s\t%s\t%d\t%s\t%s\n"
                          % (scope, key[0], key[1], key[2], table[key]))

    print("distinct warning sites in CVMFS sources: %d" % len(own))
    print("distinct warning sites in third-party code: %d (not listed below)"
          % len(other))
    print()
    print("%-42s %s" % ("category", "sites"))
    for cat, count in Counter(k[2] for k in own).most_common():
        print("%-42s %5d" % (cat, count))
    print()
    print("%-42s %s" % ("file", "sites"))
    for path, count in Counter(k[0] for k in own).most_common(args.top):
        print("%-42s %5d" % (path, count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
