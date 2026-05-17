# Sample Tag Harmonizer

Sample Tag Harmonizer is a Python project for analyzing Native Instruments WAV sample metadata and building a foundation for harmonizing third-party sample tags with NI-style categories.

## Documentation Map

Code-adjacent documentation lives next to the package it explains:

- [`src/sampletagharmonizer/parsers/README.md`](src/sampletagharmonizer/parsers/README.md): parser layer overview and RIFF/WAVE layout.
- [`src/sampletagharmonizer/parsers/wav/README.md`](src/sampletagharmonizer/parsers/wav/README.md): WAV parser behavior and tolerance rules.
- [`src/sampletagharmonizer/parsers/ni_metadata/README.md`](src/sampletagharmonizer/parsers/ni_metadata/README.md): Native Instruments ID3, GEOB, SoundInfo, and tag payload notes.
- [`src/sampletagharmonizer/parsers/msgpack_lite/README.md`](src/sampletagharmonizer/parsers/msgpack_lite/README.md): minimal MessagePack decoder details.
- [`src/sampletagharmonizer/db/README.md`](src/sampletagharmonizer/db/README.md): database schema and table responsibilities.
- [`src/sampletagharmonizer/services/README.md`](src/sampletagharmonizer/services/README.md): indexing, metadata extraction, retry, resume, and batch-commit workflows.

Project-level notes remain in `docs/`, for example Python setup instructions and future feature concepts.

## Documentation Pattern

Package-local `README.md` files should collect code-adjacent context that is useful while working inside that package. Prefer one README per package with focused sections over many tiny Markdown files.

Good candidates for these README sections are:

- binary format notes
- parser assumptions and tolerances
- observed vendor-specific quirks
- examples that explain non-obvious helper functions

Broader project documentation belongs in `docs/`. Code-adjacent package documentation belongs next to the implementation it explains.
