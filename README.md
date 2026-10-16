# 官方插件：音乐观众

This is the official source repository for `org.pupujiang.music-audience`. The MIT-licensed declarative package provides music-room persona and topic resources through the shared host plugin contract.

The package is distinct from the fabric-buyer plugin, but its full music-domain response behavior has not yet passed the host compatibility and behavior review required for Registry listing. The Registry will list a version only after those checks and its fixed Release asset have been reviewed.

## Python SDK reference

The official package remains a data-only ZIP and does not bundle the SDK. The separate `worker/music_audience/` source provides a local SDK Replay entrypoint that receives bounded anonymous context and can request model output through the host capability. Its viewer and room inputs stay untrusted, and the host retains factual checks, settlement, and sending. Install the exact SDK wheel and run its regressions with:

```powershell
python -m pip install --require-hashes -r worker/requirements.txt
python -m unittest discover -s tests -v
```

This is trusted development source only. It is not included in the data-only ZIP and does not authorize executing downloaded plugin code.

## Validate and build

Use Python 3.10 or newer:

```powershell
python scripts/package_plugins.py --check
python scripts/package_plugins.py --plugin music-audience --output dist --expected-version 1.0.0
```

The package command writes `music-audience-1.0.0.zip` and its `.sha256` sidecar to the output directory. These generated files are Release artifacts and must not be committed to this repository.

Use the `.sha256` asset attached to the GitHub Release when preparing a Registry entry. Locally generated ZIP bytes can differ across operating systems because ZIP metadata and compression implementations vary; the Release asset and its digest are authoritative.

## Publish

After an explicitly approved version is ready, push the matching `music-audience-v<version>` tag. GitHub Actions builds the ZIP and checksum from that tag and publishes both assets to its GitHub Release. A separate reviewed Registry entry is required before the host market can offer the version.

## License

This source repository is MIT licensed. The plugin package includes the same MIT license text.
