import unittest

from core.physical import pick_values, replace_pick_value, set_pick_values
from models.physical import PhysicalItem


def disc(**kw):
    return PhysicalItem(title="Disc", specs=kw.pop("specs", {}), tags=kw.pop("tags", []), **kw)


class PickListTests(unittest.TestCase):
    def test_values_of_single_and_list_fields(self):
        item = disc(package="Slipcover", specs={"audio": ["DTS 5.1", "Stereo"], "hdr": "HDR10"})
        self.assertEqual(pick_values(item, "package"), ["Slipcover"])
        self.assertEqual(pick_values(item, "audio"), ["DTS 5.1", "Stereo"])
        self.assertEqual(pick_values(item, "hdr"), ["HDR10"])
        self.assertEqual(pick_values(item, "location"), [])

    def test_rename_changes_only_discs_with_the_value(self):
        a, b = disc(distributor="Sony Pictures"), disc(distributor="Arrow")
        self.assertEqual(replace_pick_value([a, b], "distributor", "Sony Pictures", "Sony"), 1)
        self.assertEqual((a.distributor, b.distributor), ("Sony", "Arrow"))
        self.assertTrue(a.edited_locally)

    def test_merging_into_a_value_already_on_the_disc_keeps_it_once(self):
        item = disc(specs={"subtitles": ["English", "english", "French"]})
        replace_pick_value([item], "subtitles", "english", "English")
        self.assertEqual(item.specs["subtitles"], ["English", "French"])

    def test_remove(self):
        item = disc(condition="Mint", specs={"extras": ["Booklet"]}, tags=["mcu", "4k"])
        replace_pick_value([item], "condition", "Mint", None)
        replace_pick_value([item], "extras", "Booklet", None)
        replace_pick_value([item], "tags", "mcu", None)
        self.assertIsNone(item.condition)
        self.assertNotIn("extras", item.specs)
        self.assertEqual(item.tags, ["4k"])

    def test_set_empty_list_column(self):
        item = disc(tags=["x"])
        set_pick_values(item, "tags", [])
        self.assertEqual(item.tags, [])


if __name__ == "__main__":
    unittest.main()
