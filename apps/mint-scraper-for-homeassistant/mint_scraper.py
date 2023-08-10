"""Wrapper for mintapi python library to handle scraping."""

import json
import logging
import time
from os.path import exists
from typing import Any

from dateutil.parser import isoparse
from mintapi.api import Mint

logger = logging.getLogger("mintapi")
# logging.basicConfig(level=logging.DEBUG)


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
            logger.info("Using Cached MINT data - only refreshing at 4 hr intervals ")
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

    def _build_topics(self, account) -> dict:
        """Build all the various topics for a specific account"""
        topics = {
            key: value.replace(" ", "_").lower()
            for key, value in {
                "state_topic": f'mint/data/{account["fiName"]}/{account["name"]}_{account["id"]}',
                "attribute_topic": f'mint/data/{account["fiName"]}/{account["name"]}_attributes_{account["id"]}',
                "discovery_topic_balance": f'homeassistant/sensor/mint_{account["id"]}/account_balance/config',
                "discovery_topic_update": f'homeassistant/sensor/mint_{account["id"]}/last_update/config',
                "discovery_topic_error": f'homeassistant/binary_sensor/mint_{account["id"]}/error/config',
            }.items()
        }
        return topics

    def _build_attribute_payload(self, account):
        """Extract attributes from a MINT palyload."""
        keys_to_extract = [
            "availableBalance",
            "cpAccountNumberLast4",
            "currency",
            "currentBalance",
            "fiName",
            "interestRate",
            "investmentType" "name",
            "type",
            "value",
        ]  # List of keys you want to extract
        output_dict = {key: account[key] for key in keys_to_extract if key in account}
        return output_dict

    def _build_payloads(self, account, topics):
        """Build out payloads for a specific account."""

        payloads = {
            "discovery_payload_balance": self._build_discovery_payload(
                account,
                sensor_suffix="balance",
                object_id=f'mint {account["fiName"]} {account["name"]} balance',
                state_topic=topics["state_topic"],
                state_class="measurement",
                value_template="{{value_json.get('availableBalance', value_json.get('currentBalance'))}}",
                unit_of_measurement=account["currency"],
                json_attributes_template="{{value_json | tojson}}",
                json_attributes_topic=topics["attribute_topic"],
                force_update=True,
                icon=self._get_icon(account),
            ),
            "discovery_payload_update": self._build_discovery_payload(
                account,
                sensor_suffix="updated",
                state_topic=topics["state_topic"],
                device_class="timestamp",
                object_id=f'mint {account["fiName"]} {account["name"]} last update',
                value_template="{{ value_json.metaData.lastUpdatedDate | as_datetime }}",
                icon="mdi:update",
            ),
            "discovery_payload_error": self._build_discovery_payload(
                account,
                sensor_suffix="error",
                entity_category="diagnostic",
                state_topic=topics["attribute_topic"],
                sensor_type="binary_sensor",
                object_id=f'mint {account["fiName"]} {account["name"]} error',
                value_template="{{value_json.isError }}",
                payload_on="true",
                payload_off="false",
                icon="mdi:alert-circle",
            ),
            "state_payload": account,
            "attribute_payload": self._build_attribute_payload(account),
        }
        return payloads

    def _parse_mint_data(self, raw_data) -> list[dict]:
        """Prase out the mint data adding a few "extra" stuff."""
        logger.info("Parsing MINT data")

        data = []
        for x in raw_data:
            # Only get banking data
            if x["type"] in ["BankAccount", "InvestmentAccount"]:
                topics = self._build_topics(x)
                topics.update(self._build_payloads(account=x, topics=topics))
                data.append(topics)
            else:
                logger.info("   >> Not Parsing {}".format(x["type"]))
        return data

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

    def _get_icon(self, account: dict) -> str:
        """Sets the icons based on the account type..."""

        if account["type"] == "BankAccount":
            if account["bankAccountType"] == "CHECKING":
                return "mdi:checkbook"
            return "mdi:piggy-bank"
        if account["type"] == "InvestmentAccount":
            return "mdi:chart-line"
        # mdi:cash-multiple
        # mdi:cash
        # mdi:currency-usd
        # mdi:currency-eur
        # mdi:chart-line
        # mdi:chart-line-stacked
        # mdi:chart-line-variant

    def write_data_to_disk(self, raw_data: str) -> None:
        """Write the current set of data to disk."""
        with open("mint.json", "w") as mint_output:
            mint_output.write(json.dumps(raw_data))
