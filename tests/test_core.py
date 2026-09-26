import os
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core import (
    default_state,
    empty_pet,
    make_pin_hash,
    verify_pin,
    make_pet_pdf,
    make_backup_zip,
    restore_backup_bytes,
    materialize_attachments_to_files,
    make_record,
)


class PetPassportCoreTests(unittest.TestCase):
    def test_pin_roundtrip(self):
        encoded = make_pin_hash("1234")
        self.assertTrue(verify_pin("1234", encoded))
        self.assertFalse(verify_pin("0000", encoded))

    def test_pdf_and_backup_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["FLET_APP_STORAGE_DATA"] = td
            state = default_state()
            pet = empty_pet()
            pet.update({"name": "Luna", "species": "Cão", "breed": "Retriever"})
            pet["vaccines"].append(make_record(name="Raiva", date="2026-09-01", valid_until="2027-09-01"))
            photo = Path(td) / "pet_photo.jpg"
            photo.write_bytes(b"fake-photo-bytes")
            pet["photo_path"] = str(photo)
            pet["photo_name"] = "pet_photo.jpg"

            attachment_dir = Path(td) / "attachments" / pet["id"]
            attachment_dir.mkdir(parents=True, exist_ok=True)
            attachment = attachment_dir / "teste.txt"
            attachment.write_bytes(b"Pet Passport test")
            pet["documents"].append(
                make_record(
                    name="teste.txt",
                    category="Outros",
                    date="2026-09-25",
                    storage="file",
                    storage_path=str(attachment),
                    size=attachment.stat().st_size,
                    mime="text/plain",
                )
            )
            state["pets"].append(pet)

            pdf = make_pet_pdf(pet, state.get("owner", {}))
            self.assertTrue(pdf.startswith(b"%PDF-1.4"))
            self.assertIn(b"%%EOF", pdf)

            backup = make_backup_zip(state)
            restored = restore_backup_bytes(backup, "backup.zip")
            self.assertEqual(restored["pets"][0]["name"], "Luna")
            self.assertTrue(restored["pets"][0].get("photo_b64"))
            self.assertTrue(restored["pets"][0]["documents"][0].get("data_b64"))

            materialize_attachments_to_files(restored)
            restored_photo = Path(restored["pets"][0]["photo_path"])
            self.assertTrue(restored_photo.exists())
            self.assertEqual(restored_photo.read_bytes(), b"fake-photo-bytes")
            restored_path = Path(restored["pets"][0]["documents"][0]["storage_path"])
            self.assertTrue(restored_path.exists())
            self.assertEqual(restored_path.read_bytes(), b"Pet Passport test")


if __name__ == "__main__":
    unittest.main()
