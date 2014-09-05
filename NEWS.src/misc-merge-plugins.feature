The multinode and multinode_client plugins have been removed. Their
functionality is now built into rMake, and "single-node" mode has been removed.
Operators of single-node instances may need to install the
rmake-multinode-server and rmake-node packages, move node-specific
configuration from their serverrc into noderc, and ensure that the rmake-node
service is started on boot.

Authentication via the 'rbuilderUrl' serverrc option is no longer mandatory. If
it is not set, and rmakeUrl is also not set, then rmake will only listen on the
default UNIX socket at /var/lib/rmake/socket, equivalent to how rmake
previously worked without the multinode plugin. If rbuilderUrl is set and
rmakeUrl is not set, then rmake will listen both on the UNIX socket and also
HTTPS on port 9999. If rmakeUrl is explicitly set with one or more http or
https URLs, and rbuilderUrl is not set, then clients that connect remotely will
not be authenticated.
