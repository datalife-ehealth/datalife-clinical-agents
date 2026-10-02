# Security Policy

## Supported versions

This repository is in the scaffold phase. Only the latest commit on `main` is in
scope; there is no production release or security-update promise yet.

## Reporting a vulnerability

Do not open a public issue for vulnerabilities, prompt-injection bypasses that expose
data or tools, credential leaks, or unsafe agent actions. Email
`auroral.sunflower@gmail.com` with the affected commit, impact, reproduction, and
any suggested mitigation. You should receive an acknowledgement within five business
days. Please coordinate disclosure while a fix is validated. There is currently no
bug-bounty program.

Never include real patient information, live credentials, access tokens, or data
obtained from systems you are not authorized to test. Use a minimal synthetic proof
of concept. If a credential was committed, rotate it immediately; rewriting Git
history does not revoke it.
