"""Webex Calling Local Gateway (LGW) config generator for a CUBE (IOS XE), registration based trunk plus a CUCM trunk.

Ported from the Flask LGW tool (Jinja2 template). No Reflex imports.
"""

from dataclasses import dataclass, field

CUCM_SLOTS = 6

# Webex Calling networks: routed to the public gateway and trusted for SIP.
WEBEX_NETWORKS = [
    ("23.89.0.0", "255.255.0.0"),
    ("85.119.56.0", "255.255.254.0"),
    ("128.177.14.0", "255.255.255.0"),
    ("128.177.36.0", "255.255.255.0"),
    ("135.84.168.0", "255.255.248.0"),
    ("139.177.64.0", "255.255.248.0"),
    ("139.177.72.0", "255.255.254.0"),
    ("144.196.0.0", "255.255.0.0"),
    ("150.253.128.0", "255.255.128.0"),
    ("163.129.0.0", "255.255.128.0"),
    ("170.72.0.0", "255.255.0.0"),
    ("170.133.128.0", "255.255.192.0"),
    ("185.115.196.0", "255.255.252.0"),
    ("199.19.196.0", "255.255.254.0"),
    ("199.19.199.0", "255.255.255.0"),
    ("199.59.64.0", "255.255.248.0"),
]

# (key, label) of the required text fields, in form order.
REQUIRED = [
    ("tenant_id", "Tenant ID"),
    ("otg", "Trunk Group OTG/DTG"),
    ("proxy", "Outbound Proxy Address"),
    ("domain", "Registrar Domain"),
    ("lgu_raw", "Line/Port"),
    ("username", "Username"),
    ("out_interface", "Webex Bound Interface"),
    ("public_gateway", "Public Gateway IP"),
    ("cucm_dialpeer_id", "CUCM Dial Peer"),
    ("inside_interface", "CUCM Bound Interface"),
]

DEFAULTS = {
    "tenant_id": "100",
    "out_interface": "GigabitEthernet3",
    "cucm_dialpeer_id": "300",
    "inside_interface": "GigabitEthernet1",
}


class LgwError(Exception):
    pass


@dataclass
class LgwParams:
    tenant_id: str
    otg: str
    proxy: str
    domain: str
    lgu_raw: str
    username: str
    password: str
    out_interface: str
    public_gateway: str
    cucm_dialpeer_id: str
    inside_interface: str
    stun_password: str = ""
    cucm_hosts: list[tuple[str, str]] = field(default_factory=list)  # (hostname, ip), blank pairs already dropped


def validate(fields: dict[str, str], password: str) -> list[str]:
    """Problems with the form, empty when it can be generated."""
    problems = [f"{label} is required." for key, label in REQUIRED if not fields.get(key, "").strip()]
    if not password:
        problems.append("Password is required.")
    for key, label in (("tenant_id", "Tenant ID"), ("cucm_dialpeer_id", "CUCM Dial Peer")):
        value = fields.get(key, "").strip()
        if value and not (value.isdigit() and int(value) >= 1):
            problems.append(f"{label} must be a whole number of 1 or more.")
    for n in range(1, CUCM_SLOTS + 1):
        host, ip = fields.get(f"cm{n}host", "").strip(), fields.get(f"cm{n}ip", "").strip()
        if bool(host) != bool(ip):
            problems.append(f"CUCM {n} needs both a hostname and an IP, or leave both blank.")
    return problems


def build_params(fields: dict[str, str], password: str, stun_password: str) -> LgwParams:
    """Params from the form values. Raises LgwError listing every problem."""
    problems = validate(fields, password)
    if problems:
        raise LgwError(" ".join(problems))
    f = {k: v.strip() for k, v in fields.items()}
    hosts = [(f[f"cm{n}host"], f[f"cm{n}ip"]) for n in range(1, CUCM_SLOTS + 1) if f.get(f"cm{n}host")]
    return LgwParams(
        tenant_id=f["tenant_id"], otg=f["otg"], proxy=f["proxy"], domain=f["domain"], lgu_raw=f["lgu_raw"],
        username=f["username"], password=password, out_interface=f["out_interface"],
        public_gateway=f["public_gateway"], cucm_dialpeer_id=f["cucm_dialpeer_id"],
        inside_interface=f["inside_interface"], stun_password=stun_password, cucm_hosts=hosts,
    )


_TEMPLATE = """\
!!!!!! Trunk to Webex Section
!
!!!!!! Import Cisco credentials
!
!ip http client source-interface Lo0   ! Binding as needed for outbound http request.
crypto pki trustpool import clean url https://www.cisco.com/security/pki/trs/ios_core.p7b
!
!!!!!! Routes to Webex networks are needed if default route points inside.
!
{routes}
!
!!!!!! Voice Service Voip needs to be updated with Webex IPs, STUN, and SIP Requirements
!
voice service voip
 ip address trusted list
{trusted}
 mode border-element license periodicity days 1
 media statistics
 media bulk-stats
 allow-connections sip to sip
 no supplementary-service sip moved-temporarily
 no supplementary-service sip refer
 no supplementary-service sip handle-replaces
 fax protocol t38 version 0 ls-redundancy 1 hs-redundancy 1 fallback pass-through g711ulaw
 h323
  call service stop
 trace
 stun
  stun flowdata agent-id 1 boot-count 4
{stun_secret}
 sip
  asymmetric payload full
!
!!!!!! Blank Crypto TP for SIP-UA signal binding
!
crypto pki trustpoint CubeTP
 revocation-check none
!
!!!!!! SIP-UA standards.  Please validate with production items as needed.
!
sip-ua
 crypto signaling default trustpoint CubeTP cn-san-validate server
 transport tcp tls v1.2
 timers connection establish tls 5
 timers expires 90000
 retry response 2
 retry bye 2
 retry cancel 2
 retry prack 2
 retry update 4
 retry rel1xx 2
 retry notify 4
 retry refer 4
 retry info 4
 retry register 4
 retry subscribe 4
 retry options 4
!
!!!!!!! Webex only support AES 128 for crypto.
!
voice class srtp-crypto 1
 crypto 1 AES_CM_128_HMAC_SHA1_80
!
!!!!!!! Stun is required for Webex
!
voice class stun-usage 1
 stun usage firewall-traversal flowdata
 stun usage ice lite
!
!!!!!!! Codec list for G711
!
voice class codec 1
 codec preference 1 g711ulaw
!
!!!!!!! Below is the config for the Webex Trunk
!
voice class uri {tenant_id} sip
 pattern dtg={otg}
!
voice class sip-profiles {tenant_id}
 rule 10 request ANY sip-header SIP-Req-URI modify "sips:(.*)" "sip:\\1"
 rule 20 request ANY sip-header To modify "<sips:(.*)" "<sip:\\1"
 rule 30 request ANY sip-header From modify "<sips:" "<sip:\\1"
 rule 40 request ANY sip-header Contact modify "<sips:(.*)>" "<sip:\\1;transport=tls>"
 rule 50 response ANY sip-header To modify "<sips:(.*)" "<sip:\\1"
 rule 60 response ANY sip-header From modify "<sips:(.*)" "<sip:\\1"
 rule 70 response ANY sip-header Contact modify "<sips:(.*)" "<sip:\\1"
 rule 80 request ANY sip-header From modify ">" ";otg={otg}>"
 rule 90 request ANY sip-header P-Asserted-Identity modify "sips:(.*)" "sip:\\1"
!
voice class tenant {tenant_id}
 registrar dns:{domain} scheme sips expires 240 refresh-ratio 50 tcp tls
 credentials number {lgu} username {username} password 0 {password} realm BroadWorks
 authentication username {username} password 0 {password} realm BroadWorks
 authentication username {username} password 0 {password} realm {domain}
 no remote-party-id
 sip-server dns:{domain}
 connection-reuse
 srtp-crypto 1
 session transport tcp tls
 url sips
 error-passthru
 asymmetric payload full
 no update-callerid
 no session refresh
 bind control source-interface {out_interface}
 bind media source-interface {out_interface}
 no pass-thru content custom-sdp
 sip-profiles {tenant_id}
 outbound-proxy dns:{proxy}
 early-offer forced
 privacy-policy passthru
 rel1xx disable
!
voice class dpg {tenant_id}
 description Route calls to Unified CM Webex Calling trunk
!
voice class dpg {cucm_id}
 description Route calls to Webex Calling
!
dial-peer voice {tenant_id} voip
 description Inbound/Outbound Webex Calling
 max-conn 250
 destination-pattern BAD.BAD
 destination dpg {tenant_id}
 session protocol sipv2
 session target sip-server
 incoming uri request {tenant_id}
 voice-class codec 1
 voice-class stun-usage 1
 no voice-class sip localhost
 voice-class sip tenant {tenant_id}
 dtmf-relay rtp-nte
 srtp
 no vad
 fax-relay ecm disable
 fax-relay sg3-to-g3
 fax rate 14400
 fax nsf 000000
!
!!!!!! Trunk to CUCM
! The below configuration is based on adding an additional trunk to an Existing CUBE.
! This trunk will run on port 5065 on both sides. A new trunk from CUCM needs to be added using 5065 pointing to this CUBE.
!
{dns_entries}
{srv_entries}
!
voice class uri {cucm_id} sip
 pattern :5065
!
voice class tenant {cucm_id}
 listen-port non-secure 5065
 sip-server dns:wxtocucm.io
 bind control source-interface {inside_interface}
 bind media source-interface {inside_interface}
 early-offer forced
!
dial-peer voice {cucm_id} voip
 description Inbound/Outbound to CUCM for Webex Calling
 destination-pattern BAD.BAD
 destination dpg {cucm_id}
 session protocol sipv2
 session target sip-server
 incoming uri via {cucm_id}
 voice-class codec 1
 voice-class sip tenant {cucm_id}
 dtmf-relay rtp-nte
 no vad
!
voice class dpg {tenant_id}
 description Route calls to Unified CM Webex Calling trunk
 dial-peer {cucm_id}
!
voice class dpg {cucm_id}
 description Route calls to Webex Calling
 dial-peer {tenant_id}
!
"""


def generate_config(p: LgwParams) -> str:
    """The CUBE config text, passwords included."""
    password = p.password
    stun_secret = f"  stun flowdata shared-secret 0 {p.stun_password}" if p.stun_password else "!  stun flowdata shared-secret 0 <set a STUN password>"
    return _TEMPLATE.format(
        routes="\n".join(f"ip route {net} {mask} {p.public_gateway}" for net, mask in WEBEX_NETWORKS),
        trusted="\n".join(f"  ipv4 {net} {mask}" for net, mask in WEBEX_NETWORKS),
        stun_secret=stun_secret,
        tenant_id=p.tenant_id, otg=p.otg, domain=p.domain, proxy=p.proxy,
        lgu=p.lgu_raw.split("@", 1)[0], username=p.username, password=password,
        out_interface=p.out_interface, inside_interface=p.inside_interface, cucm_id=p.cucm_dialpeer_id,
        dns_entries="\n".join(f"ip host {h} {ip}" for h, ip in p.cucm_hosts),
        srv_entries="\n".join(f"ip host _sip._udp.wxtocucm.io srv 2 1 5065 {h}" for h, _ip in p.cucm_hosts),
    )
