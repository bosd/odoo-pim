# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase
from odoo.tools import SQL

from ..hooks import post_init_hook

GIN_INDEX = "res_partner__x_custom_json_attrs_index"


class TestAttributeSetJsonb(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_id = cls.env.ref("base.model_res_partner").id
        cls.attribute = cls.env["attribute.attribute"].create(
            {
                "nature": "custom",
                "name": "x_jsonb_color",
                "attribute_type": "char",
                "serialized": True,
                "model_id": cls.model_id,
                "attribute_group_id": cls.env["attribute.group"]
                .create({"name": "JSONB", "model_id": cls.model_id})
                .id,
            }
        )
        cls.serialization_field = cls.attribute.serialization_field_id

    def _query_one(self, query, *args):
        self.env.cr.execute(SQL(query, *args))
        row = self.env.cr.fetchone()
        return row and row[0]

    def _index_method(self, index_name):
        return self._query_one(
            "SELECT am.amname FROM pg_class i JOIN pg_am am ON am.oid = i.relam"
            " WHERE i.relname = %s AND i.relkind = 'i'",
            index_name,
        )

    def test_serialization_field_indexed(self):
        self.assertEqual(self.serialization_field.name, "x_custom_json_attrs")
        self.assertTrue(self.serialization_field.index)
        self.assertEqual(
            self._query_one(
                "SELECT udt_name FROM information_schema.columns"
                " WHERE table_name = 'res_partner'"
                " AND column_name = 'x_custom_json_attrs'"
            ),
            "jsonb",
        )
        self.assertEqual(self._index_method(GIN_INDEX), "gin")

    def test_serialized_value_stored(self):
        partner = self.env["res.partner"].create(
            {"name": "JSONB", "x_jsonb_color": "red"}
        )
        partner.flush_recordset()
        self.assertEqual(
            self._query_one(
                "SELECT x_custom_json_attrs->>'x_jsonb_color'"
                " FROM res_partner WHERE id = %s",
                partner.id,
            ),
            "red",
        )

    def test_post_init_hook_indexes_existing_field(self):
        self.serialization_field.write({"index": False})
        self.env.cr.execute(SQL("DROP INDEX %s", SQL.identifier(GIN_INDEX)))

        post_init_hook(self.env)

        self.assertTrue(self.serialization_field.index)
        self.assertEqual(self._index_method(GIN_INDEX), "gin")

    def test_expression_index(self):
        index_name = self.attribute._get_index_name()
        self.attribute.create_gin_index = True
        self.assertEqual(self._index_method(index_name), "btree")

        self.attribute.create_gin_index = False
        self.assertIsNone(self._index_method(index_name))
