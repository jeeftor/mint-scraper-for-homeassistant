"""Main app definition."""
from __future__ import annotations

import datetime
import json
from collections.abc import Callable

import appdaemon.plugins.mqtt.mqttapi as mqtt
from mint_scraper import MintScraper


# Alpine has some chrome driver issues where chrome/selinium/chromium/chromedriver dont match
# so we can set a symilnk betweeen crhomium and google-chrome which should make things work
from pathlib import Path

try:
    Path("/usr/bin/google-chrome").symlink_to("/usr/lib/chromium/chromium-launcher.sh")
except FileExistsError:
    pass


class MintScrapperApp(mqtt.Mqtt):
    """Appdaemon app definition."""

    def _check_args(self) -> bool:
        """Verify the right arguments are there."""
        ret = True
        self.log("-- Verifying configuration data")

        if "mint_mfa_token" not in self.args:
            self.log("Missing argument: `mint_mfa_token'")
            ret = False
        if "mint_password" not in self.args:
            self.log("Missing argument: `mint_password'")
            ret = False
        if "mint_email" not in self.args:
            self.log("Missing argument: `mint_email'")
            ret = False

        if not ret:
            self.log("-- Invalid configuration data")

        return ret

    def initialize(self) -> None:
        """Initialize the Scraping App."""
        self._check_args()
        mfa_token = self.args["mint_mfa_token"]
        mint_password = self.args["mint_password"]
        mint_email = self.args["mint_email"]

        self.set_log_level("DEBUG")

        self.log("-- Initializing Mint API")
        scraper = MintScraper(
            email=mint_email,
            password=mint_password,
            mfa_token=mfa_token,
        )

        get_data_interval = 60 * 60
        self.log(
            "-- [callback] Registering Callback: callback_get_data ever %d seconds",
            get_data_interval,
        )
        self.run_every(
            callback=self.callback_get_data,
            start=datetime.datetime.now(),
            interval=get_data_interval,
            scraper=scraper,
        )

        # Make an initial call to MINT
        scraper.scrape_or_load()
        self.log("-- [mintapi] Detected %d accounts", len(scraper.mint_data))

        self.log("-- Initializing MQTT")
        self.mqtt = self.get_plugin_api("MQTT")

        if self.mqtt.is_client_connected():
            callback_interval = 60 * 60

            # Make initial send at startup
            self.log("-- Calling send data @ startup")

            self.callback_send_data({"scraper": scraper})
            self.log(
                "-- [callback] Registering Callback: callback_send_data every: %d seconds",
                callback_interval,
            )

            self.run_every(
                callback=self.callback_send_data,
                start=datetime.datetime.now(),
                interval=callback_interval,
                scraper=scraper,
            )

    def callback_get_data(self, cb_args) -> Callable:
        """Define data retrieval callback."""
        my_scraper: MintScraper = cb_args["scraper"]
        my_scraper.scrape_or_load()

    def callback_send_data(self, cb_args) -> Callable:
        """Define MQTT Sending callback."""
        self.log("--Calling send_data callback")
        my_scraper: MintScraper = cb_args["scraper"]
        self.send_mqtt_data(scraper=my_scraper)

    def _convert_bool_to_string(self, obj: any) -> any:
        """Convert json bool values into string representations."""
        if isinstance(obj, bool):
            return str(obj).lower()
        if isinstance(obj, list | tuple):
            return [self._convert_bool_to_string(item) for item in obj]
        if isinstance(obj, dict):
            return {
                self._convert_bool_to_string(key): self._convert_bool_to_string(value)
                for key, value in obj.items()
            }
        return obj

    def send_mqtt_data(self, scraper: MintScraper) -> None:
        """Send data via MQTT."""
        self.log("send_mqtt_data::Sending discovery packets via MQTT")

        for entry in scraper.mint_data:
            # Process discovery messages and topics
            for item in ["balance", "update", "error"]:
                topic = entry[f"discovery_topic_{item}"]
                payload = json.dumps(
                    self._convert_bool_to_string(entry[(f"discovery_payload_{item}")]),
                )
                self.mqtt_publish(topic, payload)

            # Process state data
            topic = entry["state_topic"]
            payload = json.dumps(self._convert_bool_to_string(entry["state_payload"]))
            self.mqtt_publish(topic, payload)

            self.log("send_mqtt_data::Publishing State data to {}".format(topic))

            attribute_topic = entry["attribute_topic"]
            attribute_payload = json.dumps(
                self._convert_bool_to_string(entry["attribute_payload"])
            )

            self.log(
                "send_mqtt_data::Publishing attribute data to {}".format(
                    attribute_topic
                )
            )
            self.mqtt_publish(attribute_topic, attribute_payload)
