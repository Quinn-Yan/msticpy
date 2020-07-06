#  -------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for
#  license information.
#  --------------------------------------------------------------------------
"""Splunk Driver class."""
from datetime import datetime
from typing import Any, Tuple, Union, Dict, Iterable

import pandas as pd
import splunklib.client as client
import splunklib.results as results

from .driver_base import DriverBase, QuerySource
from ..._version import VERSION
from ...common.utility import export, check_kwargs
from ...common.exceptions import (
    MsticpyConnectionError,
    MsticpyNotConnectedError,
    MsticpyUserError,
)

__version__ = VERSION
__author__ = "Ashwin Patil"


SPLUNK_CONNECT_ARGS = {
    "host": "(string) The host name (the default is 'localhost').",
    "port": "(integer) The port number (the default is 8089).",
    "scheme": "('https' or 'http') The scheme for accessing the service "
    + "(the default is 'https').",
    "verify": "(Boolean) Enable (True) or disable (False) SSL verrification for "
    + "https connections. (optional, the default is True)",
    "owner": "(string) The owner context of the namespace (optional).",
    "app": "(string) The app context of the namespace (optional).",
    "sharing": "('global', 'system', 'app', or 'user') "
    + "The sharing mode for the namespace (the default is 'user').",
    "token": "(string) The current session token (optional). Session tokens can be"
    + " shared across multiple service instances.",
    "cookie": "(string) A session cookie. When provided, you don’t need to call"
    + " login(). This parameter is only supported for Splunk 6.2+.",
    "autologin": "(boolean) When True, automatically tries to log in again if"
    + " the session terminates.",
    "username": "(string) The Splunk account username, which is used to "
    + "authenticate the Splunk instance.",
    "password": "(string) The password for the Splunk account.",
}


@export
class SplunkDriver(DriverBase):
    """Driver to connect and query from Splunk."""

    _CONNECT_DEFAULTS = {"port": 8089, "http_scheme": "https", "verify": False}

    def __init__(self, **kwargs):
        """Instantiate Splunk Driver."""
        super().__init__()
        self.service = None
        self._loaded = True
        self._connected = False
        self._debug = kwargs.get("debug", False)
        self.public_attribs = {
            "client": self.service,
            "saved_searches": self._saved_searches,
            "fired_alerts": self._fired_alerts,
        }
        self.formatters = {"datetime": self._format_datetime, "list": self._format_list}

    def connect(self, connection_str: str = None, **kwargs):
        """
        Connect to Splunk via splunk-sdk.

        Returns
        -------
        [type]
            Splunk service object if connected successfully

        """
        required_args = ["host", "username", "password"]
        cs_dict: Dict[str, Any] = self._CONNECT_DEFAULTS
        if connection_str:
            cs_items = connection_str.split(";")
            cs_dict.update(
                {
                    cs_item.split("=")[0].strip(): cs_item.split("=")[1]
                    for cs_item in cs_items
                }
            )
        elif kwargs:
            cs_dict.update(kwargs)
        else:
            raise MsticpyUserError(
                "No connection details provided for Splunk connector",
                f"Required parameters are {', '.join(required_args)}",
                "All parameters:",
                *[f"{arg}: {desc}" for arg, desc in SPLUNK_CONNECT_ARGS.items()],
                title="no Splunk connection parameters",
            )

        cs_dict["port"] = int(cs_dict["port"])
        verify_opt = cs_dict.get("verify")
        if isinstance(verify_opt, str):
            cs_dict["verify"] = "true" in verify_opt.casefold()
        elif isinstance(verify_opt, bool):
            cs_dict["verify"] = verify_opt
        else:
            cs_dict["verify"] = False

        try:
            check_kwargs(cs_dict, required_args)
        except NameError as err:
            raise MsticpyUserError(*err.args, title="Required arguments missing")

        arg_dict = {
            key: val for key, val in cs_dict.items() if key in SPLUNK_CONNECT_ARGS
        }
        try:
            self.service = client.connect(**arg_dict)
        except (client.AuthenticationError, client.HTTPError) as err:
            raise MsticpyConnectionError(
                f"Error connecting to Splunk: {err}", title="Splunk connection"
            )
        self._connected = True
        print("Connected to Splunk successfully !!")

    def query(
        self, query: str, query_source: QuerySource = None
    ) -> Tuple[pd.DataFrame, Any]:
        """
        Execute splunk query and retrieve results via OneShot search mode.

        Parameters
        ----------
        query : str
            Splunk query to execute via OneShot search mode
        query_source : QuerySource
            The query definition object

        Returns
        -------
        Tuple[pd.DataFrame, Any]
            Query results in a dataframe.

        """
        del query_source
        if not self._connected:
            raise ConnectionError(
                "Source is not connected.", "Please call connect() and retry"
            )
        query_results = self.service.jobs.oneshot(query)
        reader = results.ResultsReader(query_results)
        json_response = []
        for row in reader:
            json_response.append(row)
        if isinstance(json_response, int):
            print("Warning - query did not return any results.")
            return None, json_response
        return pd.DataFrame(pd.io.json.json_normalize(json_response))

    def query_with_results(self, query: str, **kwargs) -> Tuple[pd.DataFrame, Any]:
        """
        Execute query string and return DataFrame of results.

        Parameters
        ----------
        query : str
            Query to execute against splunk instance.

        Returns
        -------
        Union[pd.DataFrame,Any]
            A DataFrame (if successful) or
            the underlying provider result if an error occurs.

        """

    @property
    def service_queries(self) -> Tuple[Dict[str, str], str]:
        """
        Return dynamic queries available on connection to service.

        Returns
        -------
        Tuple[Dict[str, str], str]
            Dictionary of query_name, query_text.
            Name of container to add queries to.

        """
        return (
            {
                search.name: search.get("search")
                for search in self.service.saved_searches
            },
            "SavedSearches",
        )

    @property
    def _saved_searches(self) -> Union[pd.DataFrame, Any]:
        """
        Return list of saved searches in dataframe.

        Returns
        -------
        pd.DataFrame
            Dataframe with list of saved searches with name and query columns.

        """
        if not self.connected:
            raise MsticpyNotConnectedError(
                "Please run the connect() method before running a query.",
                title="not connected to a workspace.",
                help_uri="TBD",
            )
        savedsearches = self.service.saved_searches

        out_df = pd.DataFrame(columns=["name", "query"])

        namelist = []
        querylist = []
        for savedsearch in savedsearches:
            namelist.append(savedsearch.name)
            querylist.append(savedsearch["search"])
        out_df["name"] = namelist
        out_df["query"] = querylist

        return out_df

    @property
    def _fired_alerts(self) -> Union[pd.DataFrame, Any]:
        """
        Return list of fired alerts in dataframe.

        Returns
        -------
        pd.DataFrame
            Dataframe with list of fired alerts with alert name and count columns.

        """
        if not self.connected:
            raise ConnectionError(
                "Source is not connected.", "Please call connect() and retry"
            )
        firedalerts = self.service.fired_alerts

        out_df = pd.DataFrame(columns=["name", "count"])

        alert_names = []
        alert_counts = []
        for alert in firedalerts:
            alert_names.append(alert.name)
            alert_counts.append(alert.count)
        out_df["name"] = alert_names
        out_df["count"] = alert_counts

        return out_df

    @staticmethod
    def _format_datetime(date_time: datetime) -> str:
        """Return datetime-formatted string."""
        return date_time.isoformat()

    @staticmethod
    def _format_list(param_list: Iterable[Any]) -> str:
        """Return formatted list parameter."""
        fmt_list = [f'"{item}"' for item in param_list]
        return ",".join(fmt_list)