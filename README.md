# Required workflows

This repository contains the shared Node.js checks and a simulated delivery pipeline for
`cicd-demo-org`. The npm and organization-policy workflows are intended for an
organization ruleset. CodeQL is called by the application as a normal reusable
workflow: CodeQL analysis is not supported as a ruleset-required workflow.

The delivery pipeline builds once, records **synthetic** vendor/QA/change
results, verifies the same build checksum at each stage, and simulates deployment
to `dev`, `test`, and `prod`. No vendor or deployment API is contacted. A green
demo is not evidence that a real security control or production deployment passed.
The `DEMO_MODE` organization variable must equal `simulation`.

The source workflow reference should be pinned to a reviewed commit SHA by
callers. For integration and operating instructions see
[governance-docs](https://github.com/cicd-demo-org/governance-docs).
