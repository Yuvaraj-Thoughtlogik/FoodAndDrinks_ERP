/** @odoo-module **/

import { SearchBar } from "@web/search/search_bar/search_bar";

// Patch SearchBar to accept 'toggler' prop for compatibility with x2many_search_view module
// Extend SearchBar.props to include toggler prop
if (SearchBar.props) {
    SearchBar.props.toggler = { type: Object, optional: true };
} else {
    SearchBar.props = {
        toggler: { type: Object, optional: true },
    };
}

