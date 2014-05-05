Added preliminary support for a 'btrfs' chroot cache. This mode uses btrfs
subvolumes for chroot dirs, and snapshots them into and out of the chrootcache
directory.
