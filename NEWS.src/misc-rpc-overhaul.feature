The RPC server architecture has been overhauled and is now separate from the main parent process.
By default a single worker process is used, which is sufficient for small installations.
Configuring additional workers is possible by setting 'rpcWorkers' in serverrc, but doing so adds a dependency on gunicorn.
