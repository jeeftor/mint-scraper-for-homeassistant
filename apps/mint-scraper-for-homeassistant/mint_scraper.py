"""Wrapper for mintapi python library to handle scraping."""

import json
import logging
import time
from os.path import exists
from typing import Any

from dateutil.parser import isoparse
from mintapi.api import Mint

logger = logging.getLogger("mintapi")


class MintScraper:
    """Define a mint scraper wrapper."""

    def __init__(self, email: str, password: str, mfa_token: str) -> None:
        """Initialize the mint account scraper."""
        self.email = email
        self.password = password
        self.mfa_token: str = mfa_token
        self.mint_data: list[str] = []

    def load_raw_scrape_data(self, file_name: str):
        """Load data and output the data age."""
        logger.info("Opening Mint data: %s", file_name)
        with open(file_name) as file:
            return json.load(file)

    def scrape_or_load(self) -> None:
        """Decides whether to scrape or load the data from the data file."""
        if exists("mint.json"):
            raw_data = self.load_raw_scrape_data("mint.json")

            # Calculate the age of the raw_data
            max_time = 0.0
            for entry in raw_data:
                timestamp: float = isoparse(
                    entry["metaData"]["lastUpdatedDate"],
                ).timestamp()
                max_time = max(max_time, timestamp)

            age = time.time() - max_time
            age_in_hours = divmod(age, 3600)[0]

            if age_in_hours > 4:
                logger.info(
                    "Mint DATA is more than 4 hours old - refreshing accounts...",
                )
                raw_data = self.scrape()
        else:
            raw_data = self.scrape()
        # Parse raw data
        self.mint_data = self._parse_mint_data(raw_data=raw_data)

    def scrape(self) -> list[dict[Any, Any]]:
        """Scrape MINT Accounts and return the results."""
        logger.info("Initializing MINT Api")
        mint = Mint(
            email=self.email,
            password=self.password,
            mfa_method="soft-token",
            mfa_token=self.mfa_token,
            headless=True,
            wait_for_sync=False,  # not options.no_wait_for_sync,
            wait_for_sync_timeout=300,  # options.wait_for_sync_timeout,
            fail_if_stale=False,  # options.fail_if_stale,
            use_chromedriver_on_path=True,  # options.use_chromedriver_on_path,
            beta=False,  # options.beta,
        )

        logger.info("Querying MINT Api")
        raw_data = mint.get_account_data(limit=5000)
        logger.info("Writing mint data to disk")
        self.write_data_to_disk(raw_data)
        return raw_data

    def _parse_mint_data(self, raw_data) -> list[dict]:
        """Prase out the mint data adding a few "extra" stuff."""
        logger.info("Parsing MINT data")
        return [
            {
                "state_topic": f'mint/data/{x["fiName"]}/{x["name"]}_{x["id"]}'.replace(
                    " ",
                    "_",
                ).lower(),
                "discovery_topic_balance": f'homeassistant/sensor/mint_{x["id"]}/account_balance/config',
                "discovery_payload_balance": self._build_discovery_payload(
                    x,
                    sensor_suffix="balance",
                    object_id=f'mint {x["fiName"]} {x["name"]} balance',
                    state_topic=f'mint/data/{x["fiName"]}/{x["name"]}_{x["id"]}'.replace(
                        " ",
                        "_",
                    ).lower(),
                    state_class="measurement",
                    value_template="{{value_json.value}}",
                    unit_of_measurement=x["currency"],
                    json_attributes_template="{{value_json | tojson}}",
                    json_attributes_topic="/mint/data/attributes",
                    force_update=True,
                    icon=self._get_icon(x),
                ),
                "discovery_topic_update": f'homeassistant/sensor/mint_{x["id"]}/last_update/config',
                "discovery_payload_update": self._build_discovery_payload(
                    x,
                    sensor_suffix="updated",
                    state_topic=f'mint/data/{x["fiName"]}/{x["name"]}_{x["id"]}'.replace(
                        " ",
                        "_",
                    ).lower(),
                    device_class="timestamp",
                    object_id=f'mint {x["fiName"]} {x["name"]} last update',
                    value_template="{{ value_json.metaData.lastUpdatedDate | as_datetime }}",
                    icon="mdi:update",
                ),
                "discovery_topic_error": f'homeassistant/binary_sensor/mint_{x["id"]}/error/config',
                "discovery_payload_error": self._build_discovery_payload(
                    x,
                    sensor_suffix="error",
                    entity_category="diagnostic",
                    state_topic=f'mint/data/{x["fiName"]}/{x["name"]}_{x["id"]}'.replace(
                        " ",
                        "_",
                    ).lower(),
                    sensor_type="binary_sensor",
                    object_id=f'mint {x["fiName"]} {x["name"]} error',
                    value_template="{{value_json.isError }}",
                    payload_on="true",
                    payload_off="false",
                    icon="mdi:alert-circle",
                ),
                "state_payload": x,
            }
            for x in raw_data
            # Only get banking data
            if x["type"] == "BankAccount"
        ]

    def _build_discovery_payload(
        self,
        account_data: str,
        sensor_suffix: str,
        state_topic: str = "",
        entity_category: str | None = None,
        state_class: str | None = None,
        sensor_type: str = "sensor",
        object_id: str | None = None,
        expire_after: str | None = None,
        force_update: bool = False,
        payload_on: str | bool | None = None,
        payload_off: str | bool | None = None,
        device_class: str | None = None,
        unit_of_measurement: str | None = None,
        value_template: str = "",
        json_attributes_template: str | None = None,
        json_attributes_topic: str | None = None,
        icon: str | None = None,
    ) -> dict:
        unique_id = f'{account_data["id"]}_{sensor_suffix}'.replace(" ", "_")

        discovery_payload = {
            "device": {
                "identifiers": [
                    # Bank name
                    account_data["fiLoginId"],
                ],
                "manufacturer": "Mint Scraper",
                "model": "Bank Account",
                "name": f"{account_data['fiName']}",
                "sw_version": "",
            },
            "name": account_data["name"].capitalize() + " " + sensor_suffix,
            "unique_id": unique_id,
            "state_topic": state_topic,
            "value_template": value_template,
            "force_update": force_update,
        }

        # set things if they exist:

        if unit_of_measurement:
            discovery_payload["unit_of_measurement"] = unit_of_measurement

        if icon:
            discovery_payload["icon"] = icon

        if payload_off:
            discovery_payload["payload_off"] = payload_off

        if entity_category:
            discovery_payload["entity_category"] = entity_category

        if object_id:
            discovery_payload["object_id"] = object_id

        if state_class:
            discovery_payload["state_class"] = state_class
        if expire_after:
            discovery_payload["expire_after"] = expire_after
        if payload_on:
            discovery_payload["payload_on"] = payload_on
        if device_class:
            discovery_payload["device_class"] = device_class

        if json_attributes_template:
            if json_attributes_topic:
                discovery_payload["json_attributes_topic"] = json_attributes_topic
            else:
                discovery_payload["json_attributes_topic"] = state_topic

            discovery_payload["json_attributes_template"] = json_attributes_template

        # Return data
        return discovery_payload

    def _get_icon(self, account_type: str) -> str:
        if account_type["bankAccountType"] == "CHECKING":
            return "mdi:checkbook"
        return "mdi:piggy-bank"

    def write_data_to_disk(self, raw_data: str) -> None:
        """Write the current set of data to disk."""
        with open("mint.json", "w") as mint_output:
            mint_output.write(json.dumps(raw_data))
