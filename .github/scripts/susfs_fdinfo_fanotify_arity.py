#!/usr/bin/env python3
"""Fix fanotify_fdinfo() arity in fs/notify/fdinfo.c after the SUSFS patch.

The gki-android13-5.15 SUSFS patch widens show_fdinfo()'s show callback to a
3-argument form ONLY under

    #if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || defined(CONFIG_KSU_SUSFS_SUS_KSTAT)

and leaves a stock-shaped #else branch in place. The fanotify section is not
touched by the patch: fanotify_fdinfo() stays 2-argument and its call site
stays `show_fdinfo(m, f, fanotify_fdinfo)`.

- With the SUSFS configs on, the widened show_fdinfo expects a 3-argument
  callback, so fanotify_fdinfo() must gain the (unused) `struct file *file`
  parameter.
- With the configs off (e.g. No Root builds, where CONFIG_KSU does not exist
  and the SUSFS Kconfig symbols cannot be enabled), the stock 2-argument
  callback is required.

Neither state compiles if fanotify_fdinfo() is rewritten unconditionally, so
rewrite it with the SAME #if/#else guard the SUSFS patch uses elsewhere in
this file:

    #if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || defined(CONFIG_KSU_SUSFS_SUS_KSTAT)
    static void fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark,
    			    struct file *file)
    #else
    static void fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark)
    #endif // #if defined(...)
    {
        <shared body - file is unused by design, the kernel does not build
         with -Wunused-parameter>

Idempotent, anchored, fails loudly if the file is in no expected shape.

Usage: susfs_fdinfo_fanotify_arity.py <kernel/common>
"""

import os
import re
import sys
from typing import NoReturn

GUARD = (
    "#if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || defined(CONFIG_KSU_SUSFS_SUS_KSTAT)\n"
)

WIDE_SHOW = re.compile(
    r"static void show_fdinfo\(struct seq_file \*m, struct file \*f,\s*\n"
    r"\s*void \(\*show\)\(struct seq_file \*m,\s*\n"
    r"\s*struct fsnotify_mark \*mark,\s*\n"
    r"\s*struct file \*file\)\)"
)
FAN_GUARDED = re.compile(
    re.escape(GUARD) + r"static void fanotify_fdinfo\("
)
FAN_3ARG_PLAIN = re.compile(
    r"static void fanotify_fdinfo\(struct seq_file \*m, struct fsnotify_mark \*mark,"
    r"\s*\n\s*struct file \*file\)\n"
)
FAN_2ARG = re.compile(
    r"static void fanotify_fdinfo\(struct seq_file \*m, struct fsnotify_mark \*mark\)\n"
)


def die(msg: str) -> NoReturn:
    sys.exit(f"ERROR: {msg}")


def guarded_rewrite() -> str:
    return (
        GUARD
        + "static void fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark,\n"
        + "\t\t\t     struct file *file)\n"
        + "#else\n"
        + "static void fanotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark)\n"
        + "#endif // #if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || defined(CONFIG_KSU_SUSFS_SUS_KSTAT)\n"
    )


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: susfs_fdinfo_fanotify_arity.py <kernel/common>")
    path = os.path.join(sys.argv[1].rstrip("/"), "fs/notify/fdinfo.c")
    if not os.path.exists(path):
        print("  fdinfo.c: not present (nothing to do)")
        return

    src = open(path, encoding="utf-8").read()

    if not WIDE_SHOW.search(src):
        print("  fdinfo.c: show_fdinfo() is not widened - nothing to do")
        return

    if FAN_GUARDED.search(src):
        print("  fdinfo.c: fanotify_fdinfo() already config-guarded")
        return

    if "static void fanotify_fdinfo(" not in src:
        print("  fdinfo.c: no fanotify_fdinfo() in this tree - nothing to do")
        return

    if FAN_3ARG_PLAIN.search(src):
        # Legacy output of the unconditional rewrite: convert it to the
        # guarded two-state form.
        src, n = FAN_3ARG_PLAIN.subn(lambda _: guarded_rewrite(), src, count=1)
    elif FAN_2ARG.search(src):
        src, n = FAN_2ARG.subn(lambda _: guarded_rewrite(), src, count=1)
    else:
        die("fdinfo.c: fanotify_fdinfo() is in an unrecognized shape")

    open(path, "w", encoding="utf-8").write(src)

    check = open(path, encoding="utf-8").read()
    if not FAN_GUARDED.search(check):
        die("fdinfo.c: fanotify_fdinfo() not config-guarded after rewrite")
    print("  fdinfo.c: fanotify_fdinfo() config-guarded (3-arg under SUSFS, 2-arg stock)")


if __name__ == "__main__":
    main()
