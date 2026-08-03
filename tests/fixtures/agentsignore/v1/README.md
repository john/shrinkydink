# `.agentsignore` conformance fixtures, version 1

This directory is the versioned, content-free fixture contract for Shrinkydink's
canonical matcher. `tree.json` describes empty files, directories, and symlinks
that the runner creates under temporary directories. Each expectation manifest
names a rules file and supplies typed (`file` or `directory`) candidate paths.
Expected results are `included`, `excluded`, or `rejected`.

`syntax.agentsignore` covers every syntax and normalization behavior documented
in `references/agentsignore.md`. `docker-agent.agentsignore` is a compatibility
fixture based on Docker Agent's first-party *Ignoring files* overview and syntax
table, reviewed 2026-08-03 at
<https://docs.docker.com/ai/docker-agent/configuration/agentsignore/>. Provenance
is pinned to source snapshot
`docker/docker-agent@7c5b33b1c177311277a3f90362faf4788e88eed2`.

Fixture schema changes require a new version directory. New cases that preserve
the schema may be added to this version. Fixture nodes never contain file
content, and reports emit only case identifiers and matching outcomes.
