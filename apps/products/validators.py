import os

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from PIL import Image


def validate_file_size(file, max_mb=5):
    if not isinstance(file, UploadedFile):
        return
    if file.size > max_mb * 1024 * 1024:
        raise ValidationError(f"Ukuran file maksimal {max_mb} MB.")


def validate_file_extension(file, allowed_extensions):
    if not isinstance(file, UploadedFile):
        return
    ext = os.path.splitext(file.name)[1].lower().lstrip(".")
    if ext not in allowed_extensions:
        daftar = ", ".join(e.upper() for e in allowed_extensions)
        raise ValidationError(f"Format file harus salah satu dari: {daftar}.")


def validate_file_content(file):
    if not isinstance(file, UploadedFile):
        return
    
    file.seek(0)
    is_pdf = file.read(5) == b"%PDF-"
    file.seek(0)
    if is_pdf:
        return
    try:
        Image.open(file).verify()
    except Exception:
        raise ValidationError("Isi file bukan PDF atau gambar yang valid.")
    finally:
        file.seek(0)