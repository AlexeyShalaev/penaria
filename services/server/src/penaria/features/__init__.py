"""The product, by feature.

- ``core/``: the feature the product exists for, the registry of the home;
- ``support/``: the features around it (identity, documents, changes, maintenance, assistant,
  devices, notifications, platform);
- ``shared/``: the shared kernel every feature may import.

Inside a feature: ``api -> use_cases -> domain``, and ``infra`` implements what ``domain`` declares.
"""
