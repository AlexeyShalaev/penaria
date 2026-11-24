# Security policy

## Supported versions

Penaria is in early development and has no release yet. Once it does, the latest minor release gets security fixes.

## Reporting a vulnerability

Do not report vulnerabilities in public issues. Report them privately through GitHub: the **Security** tab of this repository, **Report a vulnerability**.

Include what is affected, how to reproduce it and what an attacker gains. We acknowledge a report within a few days and agree on a disclosure date with you once a fix is ready. We credit reporters in the release notes unless they prefer otherwise.

## Token formats

Devices and integrations sign in to Penaria with tokens of the form `pnr_` followed by 43 letters and digits, matched by the regular expression `pnr_[0-9A-Za-z]{43}`. Secret scanners can look for it; GitHub's secret scanning takes it as a custom pattern. Anyone who finds one leaked should tell the install's owner, who revokes the device on the home's People page: its access ends at once.
