/*jsl:import ipa.js */

/*  Authors:
 *    Pavel Zuna <pzuna@redhat.com>
 *    Endi Dewata <edewata@redhat.com>
 *    Adam Young <ayoung@redhat.com>
 *
 * Copyright (C) 2010 Red Hat
 * see file 'COPYING' for use and warranty information
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

/* REQUIRES: ipa.js, details.js, search.js, add.js, facet.js, entity.js */

IPA.group = {};

IPA.group.entity = function(spec) {

    var that = IPA.entity(spec);

    that.init = function() {
        that.entity_init();

        that.builder.search_facet({
            columns: [
                'cn',
                'gidnumber',
                'description'
            ]
        }).
        details_facet({
            sections: [
                {
                    name: 'details',
                    fields: [
                        'cn',
                        {
                            type: 'textarea',
                            name: 'description'
                        },
                        'gidnumber'
                    ]
                }
            ]
        }).
        association_facet({
            name: 'member_user',
            columns:[
                'uid',
                'uidnumber',
                'mail',
                'telephonenumber',
                'title'
            ],
            adder_columns:[
                {
                    name: 'cn',
                    width: '100px'
                },
                {
                    name: 'uid',
                    primary_key: true,
                    width: '100px'
                }
            ]

        }).
        association_facet({
            name: 'memberof_group',
            associator: IPA.serial_associator
        }).
        association_facet({
            name: 'memberof_netgroup',
            associator: IPA.serial_associator
        }).
        association_facet({
            name: 'memberof_role',
            associator: IPA.serial_associator
        }).
        association_facet({
            name: 'memberof_hbacrule',
            associator: IPA.serial_associator,
            add_method: 'add_user',
            remove_method: 'remove_user'
        }).
        association_facet({
            name: 'memberof_sudorule',
            associator: IPA.serial_associator,
            add_method: 'add_user',
            remove_method: 'remove_user'
        }).
        standard_association_facets().
        adder_dialog({
            factory: IPA.group_adder_dialog,
            fields: [
                'cn',
                {
                    type: 'textarea',
                    name: 'description'
                },
                {
                    type: 'nonposix_checkbox',
                    name: 'nonposix',
                    label: IPA.messages.objects.group.posix,
                    checked: true
                },
                'gidnumber'
            ]
        });
    };

    return that;
};

IPA.group_nonposix_checkbox_widget = function (spec) {

    spec = spec || {};

    var that = IPA.checkbox_widget(spec);

    that.save = function() {
        var value = that.checkbox_save()[0];
        // convert posix into non-posix
        return [!value];
    };

    return that;
};

IPA.widget_factories['nonposix_checkbox'] = IPA.group_nonposix_checkbox_widget;
IPA.field_factories['nonposix_checkbox'] = IPA.checkbox_field;

IPA.group_adder_dialog = function(spec) {

    spec = spec || {};

    var that = IPA.entity_adder_dialog(spec);

    var init = function() {

        var posix_field = that.fields.get_field('nonposix');
        posix_field.widget.value_changed.attach(that.on_posix_change);
    };

    that.on_posix_change = function (value) {

        var gid_field = that.fields.get_field('gidnumber');
        if (value[0]) {
            gid_field.reset();
        }
        gid_field.set_enabled(!value[0]);
    };

    init();

    return that;
};

IPA.register('group', IPA.group.entity);