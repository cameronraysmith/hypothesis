# This file is part of Hypothesis, which may be found at
# https://github.com/HypothesisWorks/hypothesis/
#
# Copyright the Hypothesis Authors.
# Individual contributors are listed in AUTHORS.rst and the git log.
#
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at https://mozilla.org/MPL/2.0/.

import shutil
import tempfile
from os import getenv

import requests

from hypothesis.configuration import mkdir_p, storage_directory
from hypothesis.database import DirectoryBasedExampleDatabase


class GitHubArtifactDatabase(DirectoryBasedExampleDatabase):
    """
    A directory-based database loaded from a GitHub Actions artifact.

    This is useful for sharing example databases between CI runs and developers, allowing the latter
    to get read-only access to the former. In most cases, this will be used through the
    :class:`~hypothesis.database.MultiplexedDatabase`, by combining a local directory-based database
    with this one. For example:

    .. code-block:: python

        local = DirectoryBasedExampleDatabase(".hypothesis/examples")
        shared = GitHubArtifactDatabase("user", "repo")

        settings.register_profile("ci", database=local)
        settings.register_profile("dev", database=MultiplexedDatabase(local, shared))
        settings.load_profile("ci" if os.environ.get("CI") else "dev")

    This, combined with a CI workflow that syncs its local folder to an artifact, will
    allow developers to also get access to the examples generated by CI.

    .. note::
        This database is read-only, and will not upload any examples to the artifact. This is to


    For mono-repo support, you can provide an unique `artifact_name` (e.g. `hypofuzz-example-db-branch`).
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        artifact_name: str = "hypofuzz-example-db",
        path: str = storage_directory("ci"),
    ):
        self.owner = owner
        self.repo = repo
        self.artifact_name = artifact_name
        self.path = path

        # Get the GitHub token from the environment
        # It's unnecessary to use a token if the repo is public
        self.token = getenv("GITHUB_TOKEN")

        # We want to be lazy per conftest initialization
        self._artifact_downloaded = False

    def __repr__(self) -> str:
        return f"GitHubArtifactDatabase(owner={self.owner}, repo={self.repo}, artifact_name={self.artifact_name})"

    def _fetch_artifact(self) -> None:
        if self._artifact_downloaded:
            return

        # Get the latest artifact from the GitHub API
        try:
            res = requests.get(
                f"https://api.github.com/repos/{self.owner}/{self.repo}/actions/artifacts",
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28 ",
                    "Authorization": f"Bearer {self.token}",
                },
            )
            res.raise_for_status()
            artifacts: list[dict] = res.json()["artifacts"]
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                "Could not connect to GitHub to get the latest artifact."
            ) from e
        except requests.exceptions.HTTPError as e:
            # TODO: Be more granular
            raise RuntimeError(
                "Could not get the latest artifact from GitHub. "
                "Check that the repository exists and that you've provided a valid token (GITHUB_TOKEN)."
            ) from e

        # Get the latest artifact from the list
        artifact = sorted(
            filter(lambda a: a["name"] == self.artifact_name, artifacts),
            key=lambda a: a["created_at"],
        )[-1]

        # Download and extract the artifact into .hypothesis/ci
        with tempfile.NamedTemporaryFile() as f:
            try:
                req = requests.get(
                    artifact["archive_download_url"],
                    headers={
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "Authorization": f"Bearer {self.token}",
                    },
                    stream=True,
                    allow_redirects=True,
                )
                req.raise_for_status()
            except requests.exceptions.ConnectionError as e:
                raise RuntimeError(
                    "Could not connect to GitHub to download the artifact."
                ) from e
            except requests.exceptions.HTTPError as e:
                raise RuntimeError(
                    "Could not get the latest artifact from GitHub. "
                    "Check that the repository exists and that you've provided a valid token (GITHUB_TOKEN)."
                ) from e

            f.write(req.content)

            # Extract the artifact
            mkdir_p(self.path)
            shutil.unpack_archive(f.name, self.path, "zip")

        super().__init__(self.path)
        self._artifact_downloaded = True

    def fetch(self, key: bytes):
        self._fetch_artifact()
        # Delegate all IO to DirectoryBasedExampleDatabase
        return super().fetch(key)

    # Read-only interface
    def save(self, key: bytes, value: bytes) -> None:
        raise RuntimeError(
            "This database is read-only. Please wrap this class with ReadOnlyDatabase, i.e. ReadOnlyDatabase(GitHubArtifactsDatabase(...))."
        )

    def move(self, key: bytes, value: bytes) -> None:
        raise RuntimeError(
            "This database is read-only. Please wrap this class with ReadOnlyDatabase, i.e. ReadOnlyDatabase(GitHubArtifactsDatabase(...))."
        )

    def delete(self, key: bytes, value: bytes) -> None:
        raise RuntimeError(
            "This database is read-only. Please wrap this class with ReadOnlyDatabase, i.e. ReadOnlyDatabase(GitHubArtifactsDatabase(...))."
        )
