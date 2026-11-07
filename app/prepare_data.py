#!/usr/bin/env python3
"""One-shot permission setup for a fresh, root-owned app-data bind mount."""
import os
import stat

# Open the mounted directory itself, never a symlink or anything below it.
fd = os.open('/data', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    st = os.fstat(fd)
    if (st.st_uid, st.st_gid) != (1000, 1000):
        os.fchown(fd, 1000, 1000)
    # Do not chmod after chown: CHOWN is the only added capability. Docker's
    # fresh 0755 bind directory becomes writable by the app when it owns it.
    if not st.st_mode & stat.S_IWUSR:
        raise RuntimeError('/data must be writable by its owner')
finally:
    os.close(fd)
print('Calendar data root ready for 1000:1000')
