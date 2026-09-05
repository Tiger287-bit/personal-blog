# Vendored Python dependencies

These wheels are bundled so Arduino App Lab can provision the Brick when the
VENTUNO Q has no Internet access. They target the App Lab runtime:

- Linux aarch64
- CPython 3.13
- manylinux2014-compatible userspace

The package versions are pinned in the Brick's `requirements.txt`. The bundle
currently contains `python-can 4.6.1`, `packaging 26.3`,
`typing-extensions 4.16.0`, and `wrapt 1.17.3`. Refresh the wheels whenever
the App Lab Python runtime or a dependency version changes.
