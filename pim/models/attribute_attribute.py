# Copyright 2026 OBS Solutions B.V.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models


class AttributeAttribute(models.Model):
    """Let a PIM Manager create/edit attributes without Settings.

    ``attribute.attribute`` ``_inherits`` ``ir.model.fields``: creating or
    editing a *custom* attribute inserts/updates the backing field record,
    which Odoo gates to ``base.group_system`` (Settings) at the ORM level —
    an ACL grant alone cannot open it. A PIM Manager therefore holds the
    ``attribute.*`` ACLs (below) yet still hits
    "You are not allowed to access 'Fields' (ir.model.fields)".

    We verify the acting user's *own* right on ``attribute.attribute`` first
    (so ``sudo`` never widens who may manage attributes), then elevate only
    the field-touching write. Members of Settings and superuser flows are
    left untouched.
    """

    _inherit = "attribute.attribute"

    def _pim_manager_field_sudo(self):
        """True when the field write must be elevated for the current user."""
        return not self.env.su and not self.env.user.has_group("base.group_system")

    @api.model_create_multi
    def create(self, vals_list):
        if self._pim_manager_field_sudo():
            # Empty recordset in create() → model-level create check. Raises
            # AccessError if the user may not create attributes at all.
            self.browse().check_access("create")
            return (
                super(AttributeAttribute, self.sudo())
                .create(vals_list)
                .with_env(self.env)
            )
        return super().create(vals_list)

    def write(self, vals):
        if self._pim_manager_field_sudo():
            self.check_access("write")
            return super(AttributeAttribute, self.sudo()).write(vals)
        return super().write(vals)
