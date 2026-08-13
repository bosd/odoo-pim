# Copyright 2026 OBS Solutions B.V.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest import mock

from odoo.exceptions import AccessError
from odoo.tests import common, tagged


@tagged("post_install", "-at_install")
class TestPimAttributeManager(common.TransactionCase):
    """A PIM Manager (no Settings) may create/edit custom attributes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_id = cls.env.ref("base.model_res_partner").id
        cls.group = cls.env["attribute.group"].create(
            {"name": "PIM Group", "model_id": cls.model_id}
        )
        # Creating a manual field would otherwise commit; keep the test atomic.
        cls.env.cr.commit = mock.Mock()
        cls.pim_manager = cls.env["res.users"].create(
            {
                "name": "PIM Manager Test",
                "login": "pim_manager_test",
                "email": "pim.manager@test.odoo.com",
                "group_ids": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, cls.env.ref("pim.group_pim_manager").id),
                ],
            }
        )
        cls.plain_user = cls.env["res.users"].create(
            {
                "name": "Plain User Test",
                "login": "plain_user_test",
                "email": "plain.user@test.odoo.com",
                "group_ids": [(4, cls.env.ref("base.group_user").id)],
            }
        )
        # A PIM Manager holds no Settings access — that is the whole point.
        assert not cls.pim_manager.has_group("base.group_system")

    def _attr_vals(self, attribute_type="char"):
        return {
            "nature": "custom",
            "model_id": self.model_id,
            "attribute_group_id": self.group.id,
            "attribute_type": attribute_type,
            "field_description": f"PIM {attribute_type}",
            "name": f"x_pim_{attribute_type}",
        }

    def test_pim_manager_can_create_attribute(self):
        """PIM Manager creates a custom attribute (backing field is made)."""
        attr = (
            self.env["attribute.attribute"]
            .with_user(self.pim_manager)
            .create(self._attr_vals("char"))
        )
        self.assertEqual(attr.ttype, "char")
        self.assertTrue(attr.field_id, "The backing ir.model.fields was created")

    def test_pim_manager_can_edit_attribute(self):
        """PIM Manager edits a custom attribute (writes the backing field)."""
        attr = (
            self.env["attribute.attribute"]
            .with_user(self.pim_manager)
            .create(self._attr_vals("integer"))
        )
        attr.write({"field_description": "Renamed by PIM Manager"})
        self.assertEqual(attr.field_description, "Renamed by PIM Manager")

    def test_plain_user_cannot_create_attribute(self):
        """A user without the PIM Manager role is still refused (sudo does not
        widen who may manage attributes)."""
        with self.assertRaises(AccessError):
            self.env["attribute.attribute"].with_user(self.plain_user).create(
                self._attr_vals("float")
            )
