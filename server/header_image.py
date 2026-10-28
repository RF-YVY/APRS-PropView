"""Persistent, size-normalized custom dashboard header image."""
import asyncio
import base64
import binascii
import io
import logging
import os
import tempfile
import warnings
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def normalize_header_image(data):
    """Fit the first image frame into 192px, preserving shape and transparency."""
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError('Choose an image of 10 MB or smaller.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {'PNG', 'JPEG', 'WEBP', 'GIF', 'BMP', 'ICO'}:
                    raise ValueError('Choose a PNG, JPEG, WebP, GIF, BMP or ICO image.')
                if source.width * source.height > 25_000_000:
                    raise ValueError('Choose an image with at most 25 million pixels.')
                image = ImageOps.exif_transpose(source).convert('RGBA')
                image.thumbnail((192, 192), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format='PNG')
                return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError('Unable to read this image. Choose a valid, smaller image.') from exc


def save_header_image(path, data):
    content = normalize_header_image(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='header-image-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def register_header_image_routes(app, config_path, static_dir):
    image_path = Path(config_path).with_name('header-image.png')

    @app.get('/api/header-image')
    async def header_image():
        path = image_path if image_path.is_file() else Path(static_dir) / 'img' / 'app-icon.webp'
        return FileResponse(path, headers={'Cache-Control': 'no-store'})

    @app.post('/api/header-image')
    async def upload_header_image(request: Request):
        try:
            # Bound the encoded request as well as the decoded file.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_IMAGE_BYTES * 4 // 3 + 4096:
                    raise ValueError('Choose an image of 10 MB or smaller.')
            import json
            payload = json.loads(body)
            encoded = payload.get('data', '')
            if not isinstance(encoded, str):
                raise ValueError('Invalid image upload.')
            data = base64.b64decode(encoded.split(',', 1)[-1], validate=True)
            await asyncio.to_thread(save_header_image, image_path, data)
            return {'success': True}
        except (ValueError, binascii.Error, AttributeError):
            logger.exception('Header image upload failed')
            return JSONResponse({'success': False, 'message':
                'Unable to read this upload. Choose a valid PNG, JPEG, WebP, GIF, BMP or ICO image '
                'of 10 MB or smaller and at most 25 million pixels.'}, status_code=400)

    @app.delete('/api/header-image')
    async def reset_header_image():
        image_path.unlink(missing_ok=True)
        return {'success': True}
