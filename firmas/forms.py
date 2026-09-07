import base64
import binascii
import zlib

from django import forms


FIRMA_MAX_BYTES = 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class FirmaForm(forms.Form):
    firma = forms.CharField()
    consentimiento = forms.BooleanField(required=True)

    def clean_firma(self):
        data_url = self.cleaned_data["firma"]
        prefix = "data:image/png;base64,"
        if not data_url.startswith(prefix):
            raise forms.ValidationError("La firma debe ser una imagen PNG válida.")

        encoded = data_url[len(prefix):]
        if not encoded:
            raise forms.ValidationError("Dibuja tu firma antes de continuar.")
        if len(encoded) > ((FIRMA_MAX_BYTES + 2) // 3) * 4:
            raise forms.ValidationError("La imagen de la firma excede el tamaño permitido.")

        try:
            image = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise forms.ValidationError("La firma contiene datos base64 inválidos.")

        if not image:
            raise forms.ValidationError("Dibuja tu firma antes de continuar.")
        if len(image) > FIRMA_MAX_BYTES:
            raise forms.ValidationError("La imagen de la firma excede el tamaño permitido.")
        if not self._is_canvas_png(image):
            raise forms.ValidationError("La firma debe ser una imagen PNG válida.")
        return image

    @staticmethod
    def _is_canvas_png(image):
        if len(image) < 33 or not image.startswith(PNG_SIGNATURE):
            return False
        if image[12:16] != b"IHDR" or image[24:29] != b"\x08\x06\x00\x00\x00":
            return False
        width = int.from_bytes(image[16:20], "big")
        height = int.from_bytes(image[20:24], "big")
        if not (0 < width <= 2048 and 0 < height <= 2048 and width * height <= 2_000_000):
            return False

        offset = len(PNG_SIGNATURE)
        chunk_types = []
        compressed_pixels = []
        while offset + 12 <= len(image):
            length = int.from_bytes(image[offset:offset + 4], "big")
            end = offset + 12 + length
            if end > len(image):
                return False
            chunk_type = image[offset + 4:offset + 8]
            chunk_data = image[offset + 8:offset + 8 + length]
            expected_crc = int.from_bytes(image[offset + 8 + length:end], "big")
            if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
                return False
            chunk_types.append(chunk_type)
            if chunk_type == b"IDAT":
                compressed_pixels.append(chunk_data)
            offset = end
            if chunk_type == b"IEND":
                break
        structure_is_valid = (
            offset == len(image)
            and chunk_types[0] == b"IHDR"
            and b"IDAT" in chunk_types
            and chunk_types[-1] == b"IEND"
        )
        return structure_is_valid and FirmaForm._has_visible_pixels(
            b"".join(compressed_pixels), width, height
        )

    @staticmethod
    def _has_visible_pixels(compressed, width, height):
        expected_size = height * (1 + width * 4)
        try:
            decompressor = zlib.decompressobj()
            raw = decompressor.decompress(compressed, expected_size + 1)
        except zlib.error:
            return False
        if len(raw) != expected_size or not decompressor.eof:
            return False

        stride = width * 4
        previous = bytearray(stride)
        offset = 0
        visible = False
        for _ in range(height):
            filter_type = raw[offset]
            offset += 1
            if filter_type > 4:
                return False
            filtered = raw[offset:offset + stride]
            offset += stride
            row = bytearray(stride)
            for index, value in enumerate(filtered):
                left = row[index - 4] if index >= 4 else 0
                above = previous[index]
                upper_left = previous[index - 4] if index >= 4 else 0
                if filter_type == 1:
                    value += left
                elif filter_type == 2:
                    value += above
                elif filter_type == 3:
                    value += (left + above) // 2
                elif filter_type == 4:
                    estimate = left + above - upper_left
                    distances = (
                        abs(estimate - left),
                        abs(estimate - above),
                        abs(estimate - upper_left),
                    )
                    value += (left, above, upper_left)[distances.index(min(distances))]
                row[index] = value & 0xFF
            visible = visible or any(row[index] for index in range(3, stride, 4))
            previous = row
        return visible
