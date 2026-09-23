import unittest
from unittest import mock

from copy_custom_fields import (
    CustomFieldCopyError,
    apply_custom_field_copies,
    build_copy_plan,
    build_custom_field_patch,
    extract_set_custom_fields,
    location_scope_names,
    normalize_custom_value,
)


def _plan(source, destination, source_locations=None, destination_locations=None):
    return build_copy_plan(
        source,
        destination,
        location_scope_names(source_locations or []),
        location_scope_names(destination_locations or []),
        source_account_id="source-account",
        destination_account_id="dest-account",
    )


class NormalizeTests(unittest.TestCase):
    def test_blank_values_are_not_set(self):
        self.assertIsNone(normalize_custom_value(None))
        self.assertIsNone(normalize_custom_value(""))
        self.assertIsNone(normalize_custom_value("   "))
        self.assertIsNone(normalize_custom_value({}))
        self.assertIsNone(normalize_custom_value([]))
        self.assertIsNone(normalize_custom_value({"kitchenName": "", "note": "  "}))

    def test_false_and_zero_count_as_set(self):
        self.assertEqual(normalize_custom_value({"featured": False, "rank": 0}), {"featured": False, "rank": 0})
        self.assertEqual(extract_set_custom_fields({"customFields": {"featured": False}}), {"customFields": {"featured": False}})

    def test_metadata_drops_empty_entries(self):
        value = normalize_custom_value(
            [
                {"key": "highlight", "value": "true"},
                {"key": "seo.title", "value": "  "},
            ]
        )
        self.assertEqual(value, [{"key": "highlight", "value": "true"}])


class PlanTests(unittest.TestCase):
    def test_ignores_items_without_custom_fields(self):
        plan = _plan(
            [
                {"_id": "s1", "account": "source-account", "plu": "P1", "name": "Plain", "productType": 1},
                {
                    "_id": "s2",
                    "account": "source-account",
                    "plu": "P2",
                    "name": "Empty",
                    "productType": 1,
                    "customFields": {},
                    "metadata": [],
                },
            ],
            [
                {"_id": "d1", "account": "dest-account", "plu": "P1", "name": "Plain", "productType": 1},
            ],
        )
        self.assertEqual(plan["source_item_count"], 2)
        self.assertEqual(plan["items_with_custom_fields"], 0)
        self.assertEqual(plan["rows"], [])

    def test_copies_custom_fields_for_matching_location_item(self):
        plan = _plan(
            [
                {
                    "_id": "s1",
                    "account": "source-account",
                    "plu": "BURGER",
                    "name": "Burger",
                    "productType": 1,
                    "location": "loc-src",
                    "customFields": {"kitchenName": "Grill", "note": ""},
                }
            ],
            [
                {
                    "_id": "d1",
                    "account": "dest-account",
                    "plu": "BURGER",
                    "name": "Burger dest",
                    "productType": 1,
                    "location": "loc-dst",
                    "customFields": {"prep": "5"},
                }
            ],
            source_locations=[{"_id": "loc-src", "name": "Downtown"}],
            destination_locations=[{"_id": "loc-dst", "name": "Downtown"}],
        )
        self.assertEqual(plan["ready"], 1)
        row = plan["rows"][0]
        self.assertEqual(row["destination_id"], "d1")
        self.assertEqual(row["scope"], "Downtown")
        self.assertEqual(
            row["patch"]["customFields"],
            {"prep": "5", "kitchenName": "Grill"},
        )
        self.assertNotIn("note", row["custom_fields"]["customFields"])

    def test_account_level_item_does_not_match_location_item(self):
        plan = _plan(
            [
                {
                    "_id": "s1",
                    "account": "source-account",
                    "plu": "BURGER",
                    "name": "Burger",
                    "productType": 1,
                    "customFields": {"kitchenName": "Grill"},
                }
            ],
            [
                {
                    "_id": "d1",
                    "account": "dest-account",
                    "plu": "BURGER",
                    "name": "Burger",
                    "productType": 1,
                    "location": "loc-dst",
                    "customFields": {},
                }
            ],
            destination_locations=[{"_id": "loc-dst", "name": "Downtown"}],
        )
        self.assertEqual(plan["unmatched"], 1)
        self.assertEqual(plan["rows"][0]["scope"], "Account")

    def test_migrated_location_marker_still_matches(self):
        plan = _plan(
            [
                {
                    "_id": "s1",
                    "account": "source-account",
                    "plu": "P1",
                    "name": "Item",
                    "productType": 1,
                    "location": "loc-src",
                    "metadata": [{"key": "highlight", "value": "true"}],
                }
            ],
            [
                {
                    "_id": "d1",
                    "account": "dest-account",
                    "plu": "P1",
                    "name": "Item",
                    "productType": 1,
                    "location": "loc-dst",
                }
            ],
            source_locations=[{"_id": "loc-src", "name": "Shop #MIGRATEDTOabc123#"}],
            destination_locations=[{"_id": "loc-dst", "name": "Shop"}],
        )
        self.assertEqual(plan["ready"], 1)
        self.assertEqual(plan["rows"][0]["scope"], "Shop")
        self.assertEqual(
            plan["rows"][0]["patch"]["metadata"],
            [{"key": "highlight", "value": "true"}],
        )

    def test_unchanged_when_destination_already_matches(self):
        fields = {"customFields": {"kitchenName": "Grill"}}
        plan = _plan(
            [{"_id": "s1", "account": "source-account", "plu": "P1", "productType": 1, **fields}],
            [
                {
                    "_id": "d1",
                    "account": "dest-account",
                    "plu": "P1",
                    "productType": 1,
                    "customFields": {"kitchenName": "Grill", "extra": "keep"},
                }
            ],
        )
        self.assertEqual(plan["unchanged"], 1)
        self.assertEqual(plan["ready"], 0)
        self.assertEqual(plan["rows"][0]["patch"], {})

    def test_different_product_types_do_not_match(self):
        plan = _plan(
            [
                {
                    "_id": "s1",
                    "account": "source-account",
                    "plu": "P1",
                    "productType": 2,
                    "customFields": {"kitchenName": "Mod"},
                }
            ],
            [
                {
                    "_id": "d1",
                    "account": "dest-account",
                    "plu": "P1",
                    "productType": 1,
                }
            ],
        )
        self.assertEqual(plan["unmatched"], 1)

    def test_deleted_items_are_ignored(self):
        plan = _plan(
            [
                {
                    "_id": "s1",
                    "account": "source-account",
                    "_deleted": True,
                    "plu": "P1",
                    "productType": 1,
                    "customFields": {"kitchenName": "Gone"},
                }
            ],
            [],
        )
        self.assertEqual(plan["source_item_count"], 0)
        self.assertEqual(plan["rows"], [])

    def test_duplicate_destination_items_each_receive_a_copy(self):
        source = [
            {
                "_id": "s1",
                "account": "source-account",
                "plu": "P1",
                "productType": 1,
                "customFields": {"kitchenName": "Grill"},
            }
        ]
        destination = [
            {"_id": "d1", "account": "dest-account", "plu": "P1", "name": "A", "productType": 1},
            {"_id": "d2", "account": "dest-account", "plu": "P1", "name": "B", "productType": 1},
        ]
        plan = _plan(source, destination)
        self.assertEqual(plan["ready"], 2)
        self.assertEqual(plan["items_with_custom_fields"], 1)
        self.assertEqual({row["destination_id"] for row in plan["rows"]}, {"d1", "d2"})

    def test_metadata_merge_keeps_destination_only_keys(self):
        destination = {
            "metadata": [
                {"key": "highlight", "value": "false"},
                {"key": "seo.title", "value": "Old"},
            ]
        }
        source_fields = {"metadata": [{"key": "highlight", "value": "true"}]}
        patch = build_custom_field_patch(destination, source_fields)
        self.assertEqual(
            patch["metadata"],
            [
                {"key": "highlight", "value": "true"},
                {"key": "seo.title", "value": "Old"},
            ],
        )


class ApplyTests(unittest.TestCase):
    def test_dry_run_does_not_patch(self):
        rows = [
            {
                "status": "ready",
                "destination_id": "d1",
                "destination_name": "Burger",
                "plu": "P1",
                "name": "Burger",
                "custom_fields": {"customFields": {"kitchenName": "Grill"}},
                "fields_label": "customFields (kitchenName)",
            }
        ]
        with mock.patch("copy_custom_fields.patch_product") as patch_product:
            results = apply_custom_field_copies(rows, "dest-account", dry_run=True)
        patch_product.assert_not_called()
        self.assertTrue(results[0]["ok"])
        self.assertTrue(results[0]["dry_run"])

    def test_apply_merges_onto_live_destination_item(self):
        rows = [
            {
                "status": "ready",
                "destination_id": "d1",
                "destination_name": "Burger",
                "plu": "P1",
                "name": "Burger",
                "scope": "Account",
                "custom_fields": {"customFields": {"kitchenName": "Grill"}},
                "fields_label": "customFields (kitchenName)",
            }
        ]
        live = {
            "_id": "d1",
            "account": "dest-account",
            "_etag": "etag-1",
            "customFields": {"prep": "5"},
        }
        with mock.patch("copy_custom_fields.get_product", return_value=(live, 200)) as get_product, mock.patch(
            "copy_custom_fields.patch_product",
            return_value=({"_id": "d1"}, 200),
        ) as patch_product:
            results = apply_custom_field_copies(rows, "dest-account", dry_run=False)

        get_product.assert_called_once_with("d1")
        payload = patch_product.call_args[0][1]
        self.assertEqual(payload["customFields"], {"prep": "5", "kitchenName": "Grill"})
        self.assertEqual(patch_product.call_args[0][2], "etag-1")
        self.assertTrue(results[0]["ok"])

    def test_refuses_item_on_another_account(self):
        rows = [
            {
                "status": "ready",
                "destination_id": "d1",
                "destination_name": "Burger",
                "plu": "P1",
                "custom_fields": {"customFields": {"kitchenName": "Grill"}},
                "fields_label": "customFields (kitchenName)",
            }
        ]
        live = {"_id": "d1", "account": "someone-else", "_etag": "etag-1"}
        with mock.patch("copy_custom_fields.get_product", return_value=(live, 200)), mock.patch(
            "copy_custom_fields.patch_product"
        ) as patch_product:
            results = apply_custom_field_copies(rows, "dest-account", dry_run=False)
        patch_product.assert_not_called()
        self.assertFalse(results[0]["ok"])

    def test_same_account_is_rejected(self):
        from copy_custom_fields import _require_accounts

        with self.assertRaises(CustomFieldCopyError):
            _require_accounts("same", "same")


if __name__ == "__main__":
    unittest.main()
