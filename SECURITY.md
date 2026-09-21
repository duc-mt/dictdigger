# Security Policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
(Security tab → *Report a vulnerability*), or email
[ducmai.network@gmail.com](mailto:ducmai.network@gmail.com).

Include what you found, how to reproduce it, and the version or commit you
tested. This is a personal project, so replies are best-effort, but reports are
read and taken seriously.

## What is in scope

The program downloads web pages, API replies and an audio file from
Merriam-Webster and stores two local files (`word_history.json` and the
`.cache/` folder). Reports about the handling of that untrusted content are the
most useful, for example path traversal, unsafe URLs, unbounded downloads, or
unsafe deserialisation.

It also reads a secret, the Merriam-Webster API key (`MW_API_KEY`), from the
environment. The key is sent only as a query parameter to dictionaryapi.com and
must never reach logs, error messages, the cache or the history; a report of any
path by which it does is in scope.
