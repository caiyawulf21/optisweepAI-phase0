from __future__ import annotations

import os
import subprocess


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def main() -> int:
    subscription_id = _required_env("AZURE_SUBSCRIPTION_ID")
    resource_group = _required_env("AZURE_RESOURCE_GROUP")
    location = _required_env("AZURE_STORAGE_LOCATION")
    account_name = _required_env("AZURE_STORAGE_ACCOUNT_NAME")
    container = os.getenv("AZURE_CANONICAL_IMAGES_CONTAINER", "canonical-images")

    subprocess.run(
        [
            "az",
            "account",
            "set",
            "--subscription",
            subscription_id,
        ],
        check=True,
    )
    subprocess.run(
        [
            "az",
            "group",
            "create",
            "--name",
            resource_group,
            "--location",
            location,
        ],
        check=True,
    )
    subprocess.run(
        [
            "az",
            "storage",
            "account",
            "create",
            "--name",
            account_name,
            "--resource-group",
            resource_group,
            "--location",
            location,
            "--sku",
            "Standard_LRS",
            "--kind",
            "StorageV2",
        ],
        check=True,
    )
    connection_string = subprocess.check_output(
        [
            "az",
            "storage",
            "account",
            "show-connection-string",
            "--name",
            account_name,
            "--resource-group",
            resource_group,
            "--query",
            "connectionString",
            "--output",
            "tsv",
        ],
        text=True,
    ).strip()
    subprocess.run(
        [
            "az",
            "storage",
            "container",
            "create",
            "--name",
            container,
            "--connection-string",
            connection_string,
        ],
        check=True,
    )
    account_url = f"https://{account_name}.blob.core.windows.net"
    print("Storage account ready:")
    print(f"AZURE_STORAGE_CONNECTION_STRING={connection_string}")
    print(f"AZURE_STORAGE_ACCOUNT_URL={account_url}")
    print(f"AZURE_CANONICAL_IMAGES_CONTAINER={container}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
