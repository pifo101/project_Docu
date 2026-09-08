import zlib
from pathlib import Path

from django.core.exceptions import ValidationError


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8"
MAX_IMAGE_DIMENSION = 2048
MAX_IMAGE_PIXELS = 2_000_000


def validate_uploaded_signature(image, filename):
    extension = Path(filename).suffix.casefold()
    if extension not in (".png", ".jpg", ".jpeg"):
        raise ValidationError("La firma debe tener extensión PNG, JPG o JPEG.")

    if image.startswith(PNG_SIGNATURE):
        if extension != ".png":
            raise ValidationError("La extensión del archivo no coincide con su contenido.")
        validate_png(image)
        return "image/png"

    if image.startswith(JPEG_SIGNATURE):
        if extension not in (".jpg", ".jpeg"):
            raise ValidationError("La extensión del archivo no coincide con su contenido.")
        validate_jpeg(image)
        return "image/jpeg"

    raise ValidationError("El archivo no contiene una imagen PNG o JPEG válida.")


def validate_canvas_png(image):
    metadata = validate_png(image, require_canvas_format=True)
    if not _has_visible_rgba_pixels(metadata["raw"], metadata["width"], metadata["height"]):
        raise ValidationError("Dibuja tu firma antes de continuar.")


def validate_png(image, require_canvas_format=False):
    if len(image) < 33 or not image.startswith(PNG_SIGNATURE):
        raise ValidationError("La imagen PNG no es válida.")

    offset = len(PNG_SIGNATURE)
    chunk_types = []
    compressed_pixels = []
    header = None
    while offset + 12 <= len(image):
        length = int.from_bytes(image[offset:offset + 4], "big")
        end = offset + 12 + length
        if end > len(image):
            raise ValidationError("La imagen PNG está incompleta.")
        chunk_type = image[offset + 4:offset + 8]
        chunk_data = image[offset + 8:offset + 8 + length]
        expected_crc = int.from_bytes(image[offset + 8 + length:end], "big")
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            raise ValidationError("La imagen PNG está corrupta.")
        if not chunk_types and chunk_type != b"IHDR":
            raise ValidationError("La cabecera PNG no es válida.")
        if chunk_type == b"IHDR":
            if header is not None or len(chunk_data) != 13:
                raise ValidationError("La cabecera PNG no es válida.")
            header = chunk_data
        elif chunk_type == b"IDAT":
            compressed_pixels.append(chunk_data)
        elif chunk_type == b"IEND" and chunk_data:
            raise ValidationError("El cierre de la imagen PNG no es válido.")
        chunk_types.append(chunk_type)
        offset = end
        if chunk_type == b"IEND":
            break

    if (
        offset != len(image)
        or not chunk_types
        or b"IDAT" not in chunk_types
        or chunk_types[-1] != b"IEND"
        or header is None
    ):
        raise ValidationError("La estructura de la imagen PNG no es válida.")

    width = int.from_bytes(header[0:4], "big")
    height = int.from_bytes(header[4:8], "big")
    bit_depth, color_type, compression, filter_method, interlace = header[8:13]
    _validate_dimensions(width, height)
    valid_depths = {
        0: (1, 2, 4, 8, 16),
        2: (8, 16),
        3: (1, 2, 4, 8),
        4: (8, 16),
        6: (8, 16),
    }
    if bit_depth not in valid_depths.get(color_type, ()):
        raise ValidationError("El formato de color PNG no es válido.")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise ValidationError("La imagen PNG utiliza una codificación no admitida.")
    if require_canvas_format and (bit_depth != 8 or color_type != 6):
        raise ValidationError("La firma dibujada debe ser un PNG RGBA de 8 bits.")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_size = (width * channels * bit_depth + 7) // 8
    expected_size = height * (row_size + 1)
    raw = _decompress_exact(b"".join(compressed_pixels), expected_size)
    for row in range(height):
        if raw[row * (row_size + 1)] > 4:
            raise ValidationError("La imagen PNG contiene un filtro de fila inválido.")
    return {"width": width, "height": height, "raw": raw}


def validate_jpeg(image):
    if len(image) < 4 or not image.startswith(JPEG_SIGNATURE):
        raise ValidationError("La imagen JPEG no es válida.")

    offset = 2
    dimensions = None
    component_ids = set()
    has_scan = False
    scan_data = False
    has_quantization_table = False
    has_huffman_table = False
    supported_sof_markers = {0xC0, 0xC2}
    while offset < len(image):
        if image[offset] != 0xFF:
            if not has_scan:
                raise ValidationError("La estructura de la imagen JPEG no es válida.")
            scan_data = True
            offset += 1
            continue

        while offset < len(image) and image[offset] == 0xFF:
            offset += 1
        if offset >= len(image):
            raise ValidationError("La imagen JPEG está incompleta.")
        marker = image[offset]
        offset += 1
        if marker == 0x00:
            if not has_scan:
                raise ValidationError("La estructura de la imagen JPEG no es válida.")
            scan_data = True
            continue
        if marker == 0xD9:
            if (
                offset != len(image)
                or dimensions is None
                or not has_quantization_table
                or not has_huffman_table
                or not has_scan
                or not scan_data
            ):
                raise ValidationError("La imagen JPEG está incompleta.")
            return
        if marker in range(0xD0, 0xD8) or marker == 0x01:
            continue
        if offset + 2 > len(image):
            raise ValidationError("La imagen JPEG está incompleta.")
        length = int.from_bytes(image[offset:offset + 2], "big")
        if length < 2 or offset + length > len(image):
            raise ValidationError("La estructura de la imagen JPEG no es válida.")
        data = image[offset + 2:offset + length]
        if marker in supported_sof_markers:
            if dimensions is not None or len(data) < 9 or data[0] != 8:
                raise ValidationError("La cabecera JPEG no es válida.")
            height = int.from_bytes(data[1:3], "big")
            width = int.from_bytes(data[3:5], "big")
            component_count = data[5]
            if component_count not in (1, 3, 4) or len(data) != 6 + 3 * component_count:
                raise ValidationError("Los componentes de la imagen JPEG no son válidos.")
            component_ids = {data[index] for index in range(6, len(data), 3)}
            if len(component_ids) != component_count:
                raise ValidationError("Los componentes de la imagen JPEG no son válidos.")
            _validate_dimensions(width, height)
            dimensions = (width, height)
        elif marker == 0xDB:
            _validate_jpeg_quantization_tables(data)
            has_quantization_table = True
        elif marker == 0xC4:
            _validate_jpeg_huffman_tables(data)
            has_huffman_table = True
        elif marker == 0xDA:
            if dimensions is None or len(data) < 6:
                raise ValidationError("La cabecera de escaneo JPEG no es válida.")
            scan_components = data[0]
            if len(data) != 1 + 2 * scan_components + 3 or not 0 < scan_components <= len(component_ids):
                raise ValidationError("La cabecera de escaneo JPEG no es válida.")
            selectors = {data[index] for index in range(1, 1 + 2 * scan_components, 2)}
            if len(selectors) != scan_components or not selectors.issubset(component_ids):
                raise ValidationError("La cabecera de escaneo JPEG no es válida.")
            has_scan = True
        offset += length

    raise ValidationError("La imagen JPEG está incompleta.")


def _validate_jpeg_quantization_tables(data):
    offset = 0
    while offset < len(data):
        precision = data[offset] >> 4
        table_id = data[offset] & 0x0F
        if precision not in (0, 1) or table_id > 3:
            raise ValidationError("La tabla de cuantización JPEG no es válida.")
        offset += 1 + (64 if precision == 0 else 128)
    if offset != len(data):
        raise ValidationError("La tabla de cuantización JPEG está incompleta.")


def _validate_jpeg_huffman_tables(data):
    offset = 0
    while offset < len(data):
        if offset + 17 > len(data):
            raise ValidationError("La tabla Huffman JPEG está incompleta.")
        table_class = data[offset] >> 4
        table_id = data[offset] & 0x0F
        if table_class not in (0, 1) or table_id > 3:
            raise ValidationError("La tabla Huffman JPEG no es válida.")
        value_count = sum(data[offset + 1:offset + 17])
        offset += 17 + value_count
    if offset != len(data):
        raise ValidationError("La tabla Huffman JPEG está incompleta.")


def _validate_dimensions(width, height):
    if not (
        0 < width <= MAX_IMAGE_DIMENSION
        and 0 < height <= MAX_IMAGE_DIMENSION
        and width * height <= MAX_IMAGE_PIXELS
    ):
        raise ValidationError("La imagen excede las dimensiones permitidas.")


def _decompress_exact(compressed, expected_size):
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, expected_size + 1)
    except zlib.error as error:
        raise ValidationError("Los datos de la imagen PNG están corruptos.") from error
    if len(raw) != expected_size or not decompressor.eof or decompressor.unused_data:
        raise ValidationError("Los datos de la imagen PNG están incompletos.")
    return raw


def _has_visible_rgba_pixels(raw, width, height):
    stride = width * 4
    previous = bytearray(stride)
    offset = 0
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
        if any(row[index] for index in range(3, stride, 4)):
            return True
        previous = row
    return False
