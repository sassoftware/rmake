# rMake -- Archived Repository
**Notice: This repository is part of a Conary/rpath project at SAS that is no longer supported or maintained. Hence, the repository is being archived and will live in a read-only state moving forward. Issues, pull requests, and changes will no longer be accepted.**

Overview
--------

*rMake* is a package building tool and is part of the *conary* suite
of programs. It differs from the *cvc* tool in that it can build a
collection of packages in a set of related builds, and it builds a chroot
based on the build requirements of the package.  Packages are built and
stored in a local repository until you wish to commit them.

After packages have been built and stored into this exclusive rmake local
repository, they are then cloned from this repository to your main repository
upon committing them. For more information about the architecture of rMake,
see the rMake developer documentation.
