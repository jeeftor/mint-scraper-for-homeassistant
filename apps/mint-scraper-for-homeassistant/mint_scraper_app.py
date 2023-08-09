"""Main app definition."""
from __future__ import annotations

import datetime
import json
import os
from collections.abc import Callable

import appdaemon.plugins.mqtt.mqttapi as mqtt
from mint_scraper import MintScraper


from pathlib import Path
try:   
    # There seem to be some issues in Alpine where the chromium and chromium-webdriver and selinium don't fulyl match
    # by symlinking chromium to google-chrome we can solve that issue and not have things crash
    Path( '/usr/bin/google-chrome').symlink_to( '/usr/lib/chromium/chromium-launcher.sh')
except FileExistsError:
    pass


dir_path = os.path.dirname(os.path.realpath(__file__))


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

        self.log("-- Initializing Mint API")
        self.log(f"PATH {dir_path}")
        scraper = MintScraper(
            email=mint_email,
            password=mint_password,
            mfa_token=mfa_token,
        )

        self.log("-- Registering Callback: callback_get_data")
        self.run_hourly(
            callback=self.callback_get_data,
            start=datetime.datetime.now(),
            scraper=scraper,
        )
        self.log("-- Registered...")
        self.log(scraper)

        scraper.scrape_or_load()
        self.log("::mintapi... Detected %d accounts", len(scraper.mint_data))

        self.log("-- Initializing MQTT")
        self.mqtt = self.get_plugin_api("MQTT")

        if self.mqtt.is_client_connected():
            self.log("-- Registering Callback: callback_send_data")

            # self.run_every(

    def callback_get_data(self, cb_args) -> Callable:
        """Define data retrieval callback."""
        my_scraper: MintScraper = cb_args["scraper"]
        my_scraper.scrape_or_load()

    def callback_send_data(self, cb_args) -> Callable:
        """Define MQTT Sending callback."""
        my_scraper: MintScraper = cb_args["scraper"]
        self.send_mqtt_data(scraper=my_scraper)

    def _convert_bool_to_string(self, obj):
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

            self.log("send_mqtt_data::Publishing State data")
            self.mqtt_publish(topic, payload)
