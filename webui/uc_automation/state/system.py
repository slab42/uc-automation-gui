"""States for CUCM > System: audio codec preference lists, regions, locations, device pools."""

from ..backend import cucm_system as s
from .crud import CrudMixin, DepCheckMixin, ResourceSpec
from .cucm import CucmState

CODEC_LISTS = ResourceSpec(
    noun="audio codec preference list",
    key="name",
    fields=s.CODEC_LIST_FIELDS,
    export_prefix="audio_codec_preference_lists",
    template_csv=(
        "name,description,codecs\n"
        "Standard-G711,Standard configuration,G.711 ulaw 64k;G.729;G.722\n"
        "Premium-Codecs,Premium audio quality,G.722;G.711 ulaw 64k;G.711 alaw 64k;G.729\n"
    ),
    bulk_template_csv="name\nStandard-G711\nPremium-Codecs\n",
    list_fn=s.list_codec_lists, add_fn=s.add_codec_list, update_fn=s.update_codec_list,
    remove_fn=s.remove_codec_list,
    add_defaults={"name": "", "description": "", "codecs": ""},
)

REGIONS = ResourceSpec(
    noun="region",
    key="name",
    fields=s.REGION_FIELDS,
    export_prefix="regions",
    template_csv="name,defaultCodec\nREG-HQ,\nREG-Branch,\n",
    bulk_template_csv="name\nREG-HQ\nREG-Branch\n",
    list_fn=s.list_regions, add_fn=s.add_region, update_fn=s.update_region, remove_fn=s.remove_region,
    add_defaults={"name": "", "defaultCodec": ""},
)

LOCATIONS = ResourceSpec(
    noun="location",
    key="name",
    fields=s.LOCATION_FIELDS,
    export_prefix="locations",
    template_csv="name,withinAudioBandwidth,withinVideoBandwidth\nLOC-HQ,512,-1\nLOC-Branch,256,-1\n",
    bulk_template_csv="name\nLOC-HQ\nLOC-Branch\n",
    list_fn=s.list_locations, add_fn=s.add_location, update_fn=s.update_location, remove_fn=s.remove_location,
    add_defaults={"name": "", "withinAudioBandwidth": "512", "withinVideoBandwidth": "-1"},
)

DEVICE_POOLS = ResourceSpec(
    noun="device pool",
    key="name",
    fields=s.DEVICE_POOL_FIELDS,
    export_prefix="device_pools",
    template_csv=(
        "name,regionName,locationName,callManagerGroupName,dateTimeSettingName,srstName\n"
        "DP-HQ,REG-HQ,LOC-HQ,Default,CMLocal,Disable\n"
    ),
    bulk_template_csv="name\nDP-HQ\nDP-Branch\n",
    list_fn=s.list_device_pools, add_fn=s.add_device_pool, update_fn=s.update_device_pool,
    remove_fn=s.remove_device_pool,
    add_defaults={"name": "", "regionName": "Default", "locationName": "", "callManagerGroupName": "Default",
                  "dateTimeSettingName": "CMLocal", "srstName": "Disable"},
)


class CodecListsState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return CODEC_LISTS


class RegionsState(CucmState, CrudMixin, DepCheckMixin):
    def _spec(self) -> ResourceSpec:
        return REGIONS

    def _dep_fn(self):
        return s.find_region_usage


class LocationsState(CucmState, CrudMixin, DepCheckMixin):
    def _spec(self) -> ResourceSpec:
        return LOCATIONS

    def _dep_fn(self):
        return s.find_location_usage


class DevicePoolsState(CucmState, CrudMixin, DepCheckMixin):
    def _spec(self) -> ResourceSpec:
        return DEVICE_POOLS

    def _dep_fn(self):
        return s.find_device_pool_usage
