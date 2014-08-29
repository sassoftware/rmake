The multinode and multinode_client plugins have been removed. Their
functionality is now built into rMake, and "single-node" mode has been removed.
Operators of single-node instances may need to install the
rmake-multinode-server and rmake-node packages, move node-specific
configuration from their serverrc into noderc, and ensure that the rmake-node
service is started on boot.

rMake servers no longer authenticate clients unless an explicit rbuilderUrl
configuration option has been set.
