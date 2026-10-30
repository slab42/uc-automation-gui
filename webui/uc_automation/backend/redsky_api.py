"""RedSky REST client for the web UI: errors, login and the E911 geography, networking and alert calls.

Written for this app (redsky/redskyAPI.py was used as reference only). Every call either returns its
result or raises RedskyError with a message meant for the user, so the run loops can show it per row.
Access tokens last 15 minutes; the client logs in again when the token is near expiry.
"""

from datetime import datetime, timedelta

import requests

from .errors import UserError

REDSKY_BASE_URL = "https://api.wxc.e911cloud.com"


class RedskyError(UserError):
    pass


class RedskyClient:
    def __init__(self, username: str, password: str, org_id: str, base_url: str = REDSKY_BASE_URL):
        self.username = username
        self.password = password
        self.org_id = org_id
        self.base_url = base_url
        self.session = requests.Session()
        self._expiry: datetime | None = None
        self._login()

    # --- plumbing ---

    def _login(self) -> None:
        try:
            resp = self.session.post(f"{self.base_url}/auth-service/login",
                                     json={"username": self.username, "password": self.password}, timeout=15)
        except requests.exceptions.ConnectTimeout:
            raise RedskyError("Timed out connecting to RedSky")
        except requests.exceptions.RequestException as e:
            raise RedskyError(f"Cannot reach RedSky ({e.__class__.__name__})")
        if resp.status_code in (400, 401, 403):
            raise RedskyError(f"Login failed (HTTP {resp.status_code}). Check the username and password.")
        if not resp.ok:
            raise RedskyError(f"Login failed (HTTP {resp.status_code}): {resp.text[:200]}")
        token = resp.json().get("accessToken")
        if not token:
            raise RedskyError("Login response had no accessToken.")
        self.session.headers["Authorization"] = f"Bearer {token}"
        self._expiry = datetime.utcnow() + timedelta(minutes=14, seconds=30)

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        if self._expiry and datetime.utcnow() >= self._expiry:
            self._login()
        try:
            return self.session.request(method, f"{self.base_url}{path}", timeout=30, **kwargs)
        except requests.exceptions.Timeout:
            raise RedskyError("Timed out talking to RedSky")
        except requests.exceptions.RequestException as e:
            raise RedskyError(f"Cannot reach RedSky ({e.__class__.__name__})")

    @staticmethod
    def _ok(resp: requests.Response) -> requests.Response:
        if not resp.ok:
            raise RedskyError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp

    def _list_paged(self, path: str, params: dict) -> list[dict]:
        """Page through a list endpoint. Handles a plain array or a {'content': [...]} page."""
        items: list[dict] = []
        page, size = 1, 100
        while True:
            resp = self._ok(self._request("GET", path, params={**params, "page": page, "pageSize": size,
                                                               "direction": "ASC", "searchTerm": ""}))
            data = resp.json()
            batch = data.get("content", []) if isinstance(data, dict) else data
            items.extend(batch)
            if len(batch) < size:
                return items
            page += 1

    def _create(self, path: str, payload, label: str, params: dict | None = None) -> tuple[str, str]:
        """POST a create request. Returns (new id or '', detail)."""
        resp = self._ok(self._request("POST", path, json=payload, params=params))
        try:
            data = resp.json()
        except ValueError:
            data = {}
        new_id = data.get("id", "") if isinstance(data, dict) else ""
        return new_id, f"Created {label}" + (f" (id {new_id})" if new_id else "")

    @staticmethod
    def _optional(payload: dict, **fields) -> dict:
        payload.update({k: v for k, v in fields.items() if v not in (None, "")})
        return payload

    @staticmethod
    def _geo_check(data: dict) -> None:
        """RedSky answers 200 with ambiguous / addressInvalid instead of creating the object."""
        if data.get("ambiguous"):
            candidates = "; ".join(str(c) for c in (data.get("addressList") or [])[:3])
            raise RedskyError("Address is ambiguous (matches multiple candidates)"
                              + (f": {candidates}" if candidates else ""))
        if data.get("addressInvalid"):
            raise RedskyError("Address is invalid (RedSky could not validate it)")

    # --- geography ---

    def _list_parent(self, kind: str, parent_id: str) -> list[dict]:
        return self._list_paged(f"/geography-service/{kind}/parent/{parent_id}",
                                {"sortBy": "name", "origin": "default"})

    def list_buildings(self) -> list[dict]:
        return self._list_parent("buildings", self.org_id)

    def list_locations(self, parent_id: str | None = None) -> list[dict]:
        """Locations directly under a Building id (default: the organization)."""
        return self._list_parent("locations", parent_id or self.org_id)

    def list_all_locations(self) -> list[tuple[str, dict]]:
        """(building name, location) for every location; building name is '' for org-level locations."""
        found = [("", loc) for loc in self.list_locations()]
        for building in self.list_buildings():
            found.extend((building.get("name", ""), loc) for loc in self.list_locations(building["id"]))
        return found

    def add_building(self, name: str, full_address: str, supplemental_data: str = "") -> str:
        payload = {"name": name, "parentOrganizationUnitId": self.org_id, "fullAddress": full_address,
                   "latitude": "", "longitude": "", "supplementalData": supplemental_data, "origin": "default"}
        data = self._ok(self._request("POST", "/geography-service/buildings", json=payload)).json()
        self._geo_check(data)
        building = data.get("orgUnitTO") or {}
        return f"Created building {building.get('name', name)} (id {building.get('id', '?')})"

    def add_location(self, name: str, parent_id: str, **optional: str) -> str:
        """optional: fullAddress, info, alternateId, callbackNumber, htmlLinkUrl, htmlLinkName, orgNameOverride."""
        payload = {"name": name, "organizationUnitId": parent_id}
        payload.update({k: v for k, v in optional.items() if v})
        data = self._ok(self._request("POST", "/geography-service/locations", json=payload)).json()
        self._geo_check(data)
        erl = data.get("erlTO")
        if not erl:
            raise RedskyError("Response missing erlTO")
        return f"Created location {erl.get('name', name)} (id {erl.get('id', '?')})"

    # --- networking ---

    def list_network_switches(self) -> list[dict]:
        return self._list_paged(f"/networking-service/networkSwitch/company/{self.org_id}", {"sortBy": "location"})

    def add_network_switch(self, chassis_id: str, location_id: str | None = None,
                           description: str | None = None) -> tuple[str, str]:
        payload = self._optional({"companyId": self.org_id, "chassisId": chassis_id},
                                 description=description, locationId=location_id)
        return self._create("/networking-service/networkSwitch", payload, f"switch {chassis_id}",
                            params={"companyId": self.org_id})

    def add_network_switch_port(self, port_id: str, network_switch_id: str, location_id: str | None = None,
                                description: str | None = None) -> tuple[str, str]:
        payload = self._optional({"portId": port_id, "networkSwitchId": network_switch_id},
                                 description=description, erlId=location_id)
        return self._create("/networking-service/networkSwitchPort", payload, f"switch port {port_id}")

    def add_bssid(self, bssid: str, location_id: str | None = None, description: str | None = None,
                  masking: bool | None = None) -> tuple[str, str]:
        payload = self._optional({"bssid": bssid, "orgId": self.org_id},
                                 locationId=location_id, description=description)
        if masking is not None:
            payload["bssidMasking"] = masking
        return self._create("/networking-service/bssid", payload, f"BSSID {bssid}")

    def list_ip_ranges(self) -> list[dict]:
        """Private IP ranges of the organization. The list endpoint is not documented in the reference JSON, so a few
        likely shapes are tried in turn; `ip_list_used` records the one that answered."""
        org = self.org_id
        attempts = [
            (f"/networking-service/ipRange/company/{org}", {"sortBy": "ipAddressLow"}),
            (f"/networking-service/ipRange/company/{org}", {"sortBy": "location"}),
            (f"/networking-service/ipRange/company/{org}", {}),
            ("/networking-service/ipRange", {"companyId": org}),
        ]
        errors = []
        for path, params in attempts:
            try:
                found = self._list_paged(path, params)
            except RedskyError as e:
                errors.append(f"{path} {params}: {e}")
                continue
            self.ip_list_used = f"{path} {params}"
            return found
        raise RedskyError("Could not list the private IP ranges. Tried: " + " | ".join(errors))

    def add_ip_range(self, ip_low: str, ip_high: str, location_id: str | None = None,
                     description: str | None = None) -> tuple[str, str]:
        payload = self._optional({"ipAddressLow": ip_low, "ipAddressHigh": ip_high},
                                 description=description, locationId=location_id)
        return self._create("/networking-service/ipRange", payload, f"IP range {ip_low}-{ip_high}",
                            params={"companyId": self.org_id})

    def add_public_ip_range(self, ip_low: str, ip_high: str, description: str | None = None) -> tuple[str, str]:
        payload = self._optional({"companyId": self.org_id, "ipAddressLow": ip_low, "ipAddressHigh": ip_high},
                                 description=description)
        return self._create("/networking-service/publicIpRange", payload, f"public IP range {ip_low}-{ip_high}",
                            params={"companyId": self.org_id})

    # --- alerts ---

    def list_alert_types(self) -> dict[str, str]:
        """{machine name: display text}."""
        return self._ok(self._request("GET", "/admin-service/alert-type")).json()

    def list_alert_templates(self) -> tuple[list[dict], str]:
        """The organization's templates plus the system ones. Returns (templates, note); note is non-empty when
        the account may not read the system templates (HTTP 403) and only its own were returned."""
        params = {"sortBy": "name"}
        templates = self._list_paged(f"/admin-service/alert-template/company/{self.org_id}", params)
        try:
            templates += self._list_paged("/admin-service/alert-template/system", params)
        except RedskyError as e:
            if "HTTP 403" not in str(e):
                raise
            return templates, "System alert templates are not available to this account (HTTP 403)"
        return templates, ""

    def add_alert_subscription(self, name: str, alert_type: tuple[str, str], template_id: str | None = None,
                               emails=(), sms=(), timezone: str | None = None, all_corporate: bool = False,
                               all_personal: bool = False) -> tuple[str, str]:
        payload = self._optional(
            {"name": name, "companyId": self.org_id,
             "alertTypeTO": {"name": alert_type[0], "text": alert_type[1]},
             "emailRecipients": [{"email": e} for e in emails],
             "smsRecipients": [{"phoneNumber": n} for n in sms],
             "allCorporateLocations": bool(all_corporate), "allPersonalLocations": bool(all_personal)},
            templateId=template_id, timezone=timezone)
        return self._create("/admin-service/alertSubscription", payload, f"alert subscription {name}")

    def set_alert_subscription_filters(self, subscription_id: str, filters: list[tuple[str, str]]) -> str:
        """filters: (ou_id, 'BUILDING' | 'LOCATION')."""
        payload = [{"subscriptionId": subscription_id, "ouId": ou_id, "filterType": kind} for ou_id, kind in filters]
        return self._create(f"/admin-service/alertSubscription/{subscription_id}/filters", payload,
                            f"{len(payload)} filter(s)")[1]

    def list_alert_subscriptions(self) -> list[dict]:
        return self._list_paged(f"/admin-service/alertSubscription/company/{self.org_id}", {"sortBy": "name"})

    def list_alert_subscription_filters(self, subscription_id: str) -> list[dict]:
        return self._list_paged(f"/admin-service/alertSubscription/{subscription_id}/filters", {"sortBy": "ouId"})


def check_login(username: str, password: str, org_id: str) -> int:
    """Log in, then list the organization's buildings. Returns the building count.

    Raises RedskyError for a bad login, an unusable organization ID or a network problem."""
    client = RedskyClient(username, password, org_id)
    try:
        return len(client.list_buildings())
    except RedskyError as e:
        raise RedskyError(f"Login worked but the organization ID was not accepted. {e}")
