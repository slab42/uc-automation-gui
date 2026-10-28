"""State for CUCM > Call Routing > Calling Search Spaces."""

from ..backend import cucm_routing as r
from .crud import CrudMixin, ResourceSpec
from .cucm import CucmState

SPEC = ResourceSpec(
    noun="calling search space",
    key="name",
    fields=r.CSS_FIELDS,
    export_prefix="calling_search_spaces",
    template_csv=(
        "name,description,members\n"
        "CSS-Internal,Internal calling,PT-Internal\n"
        "CSS-National,National calling,PT-Internal;PT-Local\n"
    ),
    bulk_template_csv="name\nCSS-Internal\nCSS-National\n",
    list_fn=r.list_css,
    add_fn=r.add_css,
    update_fn=r.update_css,
    remove_fn=r.remove_css,
    add_defaults={"name": "", "description": "", "members": ""},
)


class CssState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return SPEC
