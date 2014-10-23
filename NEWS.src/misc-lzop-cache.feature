Added a 'lzop' type of chrootcache that produces a .tar.lzo archive of the
contents. This is much faster than the gzip compression of the 'local'
chrootcache type, but produces slightly larger archives.

All chrootcache types now support partial restores. The cached chroot with the
largest subset of troves from the desired set will be restored, and then the
remaining troves will be installed on top of it.
