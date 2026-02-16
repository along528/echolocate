"""FMA Full Dataset Extraction from GCS to GCS.

Step 2 of 2: Reads the fma_full.zip from GCS and extracts MP3s to GCS.
Use download_to_gcs.sh first to transfer the zip file to GCS.

Uses ZIP central directory + GCS range reads for random-access extraction.
Resume is near-instant: only reads ~10MB central directory + lists existing files.
"""

import os
import bz2
import struct
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import storage

BUCKET_NAME = os.environ["BUCKET_NAME"]
ZIP_BLOB = os.environ.get("ZIP_BLOB", "fma-source/os.unil.cloud.switch.ch/fma/fma_full.zip")
PREFIX = os.environ.get("PREFIX", "fma/fma_full/")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "32"))

# ZIP format constants
EOCD_SIGNATURE = b"\x50\x4b\x05\x06"
EOCD64_SIGNATURE = b"\x50\x4b\x06\x06"
EOCD64_LOCATOR_SIGNATURE = b"\x50\x4b\x06\x07"
CD_SIGNATURE = b"\x50\x4b\x01\x02"
LOCAL_HEADER_SIGNATURE = b"\x50\x4b\x03\x04"
EOCD_MIN_SIZE = 22
EOCD_MAX_COMMENT = 65535
EOCD64_LOCATOR_SIZE = 20
EOCD64_MIN_SIZE = 56

# Stats
stats = {"uploaded": 0, "skipped": 0, "errors": 0, "pending": 0}


class ZipEntry:
    """A file entry parsed from the ZIP central directory."""
    __slots__ = ("name", "compress_method", "compressed_size",
                 "uncompressed_size", "local_header_offset")

    def __init__(self, name, compress_method, compressed_size,
                 uncompressed_size, local_header_offset):
        self.name = name
        self.compress_method = compress_method
        self.compressed_size = compressed_size
        self.uncompressed_size = uncompressed_size
        self.local_header_offset = local_header_offset


MAX_RETRIES = 3
READ_TIMEOUT = 300  # seconds


def range_read(blob, start: int, end: int) -> bytes:
    """Read a byte range from a GCS blob. end is exclusive. Retries on failure."""
    for attempt in range(MAX_RETRIES):
        try:
            return blob.download_as_bytes(
                start=start, end=end - 1, timeout=READ_TIMEOUT
            )
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                print(f"  Range read retry {attempt + 1}/{MAX_RETRIES} "
                      f"(bytes {start}-{end}): {e}")
                time.sleep(wait)
            else:
                raise


def find_eocd(blob, zip_size: int) -> tuple:
    """Find and parse the End of Central Directory record.

    Returns (cd_offset, cd_size, total_entries).
    Handles both standard EOCD and ZIP64 EOCD.
    """
    # Read the last 64KB + EOCD size to find the EOCD signature
    search_size = min(zip_size, EOCD_MIN_SIZE + EOCD_MAX_COMMENT)
    tail = range_read(blob, zip_size - search_size, zip_size)

    # Search backwards for EOCD signature
    eocd_pos = tail.rfind(EOCD_SIGNATURE)
    if eocd_pos == -1:
        raise ValueError("Could not find EOCD signature in zip file")

    # Parse standard EOCD (22 bytes minimum)
    eocd = tail[eocd_pos:eocd_pos + EOCD_MIN_SIZE]
    if len(eocd) < EOCD_MIN_SIZE:
        raise ValueError("EOCD record too short")

    (_, disk_num, disk_cd, num_entries_disk, num_entries_total,
     cd_size, cd_offset, comment_len) = struct.unpack_from("<4sHHHHIIH", eocd)

    # Check for ZIP64
    is_zip64 = (cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF or
                num_entries_total == 0xFFFF)

    if is_zip64:
        print("Detected ZIP64 format")
        # Look for ZIP64 EOCD locator before the EOCD
        # The locator is 20 bytes and sits right before the EOCD
        abs_eocd_pos = zip_size - search_size + eocd_pos
        locator_pos = abs_eocd_pos - EOCD64_LOCATOR_SIZE
        locator_data = range_read(blob, locator_pos,
                                  locator_pos + EOCD64_LOCATOR_SIZE)

        if locator_data[:4] != EOCD64_LOCATOR_SIGNATURE:
            raise ValueError("Could not find ZIP64 EOCD locator")

        (_, eocd64_disk, eocd64_offset, total_disks) = struct.unpack_from(
            "<4sIQI", locator_data)

        # Read ZIP64 EOCD
        eocd64_data = range_read(blob, eocd64_offset,
                                 eocd64_offset + EOCD64_MIN_SIZE)

        if eocd64_data[:4] != EOCD64_SIGNATURE:
            raise ValueError("Could not find ZIP64 EOCD record")

        # ZIP64 EOCD: sig(4s) size(Q) ver_made(H) ver_need(H) disk(I) disk_cd(I)
        #             entries_disk(Q) entries_total(Q) cd_size(Q) cd_offset(Q)
        (_, eocd64_size, _, _, _, _,
         _, num_entries_total,
         cd_size, cd_offset) = struct.unpack_from("<4sQ2H2I4Q", eocd64_data)

    print(f"Central directory: offset={cd_offset}, size={cd_size}, "
          f"entries={num_entries_total}")
    return cd_offset, cd_size, num_entries_total


def parse_central_directory(blob, cd_offset: int, cd_size: int) -> list:
    """Parse the central directory and return ZipEntry list for MP3 files."""

    # Download central directory in chunks to avoid huge single reads
    CHUNK = 16 * 1024 * 1024  # 16MB chunks
    cd_data = bytearray()
    remaining = cd_size
    offset = cd_offset

    print(f"Downloading central directory ({cd_size / 1e6:.1f} MB)...")
    while remaining > 0:
        read_size = min(CHUNK, remaining)
        chunk = range_read(blob, offset, offset + read_size)
        cd_data.extend(chunk)
        offset += read_size
        remaining -= read_size
        if cd_size > CHUNK:
            print(f"  Downloaded {len(cd_data) / 1e6:.1f} / {cd_size / 1e6:.1f} MB")

    entries = []
    pos = 0
    total_parsed = 0

    while pos < len(cd_data):
        # Check signature
        if cd_data[pos:pos + 4] != CD_SIGNATURE:
            break

        # Parse central directory file header (46 bytes fixed)
        if pos + 46 > len(cd_data):
            break

        # Central directory file header (46 bytes fixed):
        # sig(4s) ver_made(H) ver_need(H) flags(H) method(H) mod_time(H) mod_date(H)
        # crc32(I) comp_size(I) uncomp_size(I)
        # name_len(H) extra_len(H) comment_len(H) disk_start(H)
        # internal_attr(H) external_attr(I) local_header_offset(I)
        (_, version_made, version_needed, flags, compress_method,
         mod_time, mod_date, crc32, compressed_size, uncompressed_size,
         name_len, extra_len, comment_len, disk_start,
         internal_attr, external_attr,
         local_header_offset) = struct.unpack_from(
            "<4s6H3I5HII", cd_data, pos)

        name_bytes = cd_data[pos + 46:pos + 46 + name_len]
        name = name_bytes.decode("utf-8", errors="replace")

        # Handle ZIP64 extended information in extra field
        if (compressed_size == 0xFFFFFFFF or uncompressed_size == 0xFFFFFFFF or
                local_header_offset == 0xFFFFFFFF):
            extra_data = cd_data[pos + 46 + name_len:
                                 pos + 46 + name_len + extra_len]
            ep = 0
            while ep + 4 <= len(extra_data):
                ext_id, ext_size = struct.unpack_from("<HH", extra_data, ep)
                if ext_id == 0x0001:  # ZIP64 extra field
                    ext_pos = ep + 4
                    if uncompressed_size == 0xFFFFFFFF and ext_pos + 8 <= ep + 4 + ext_size:
                        uncompressed_size = struct.unpack_from(
                            "<Q", extra_data, ext_pos)[0]
                        ext_pos += 8
                    if compressed_size == 0xFFFFFFFF and ext_pos + 8 <= ep + 4 + ext_size:
                        compressed_size = struct.unpack_from(
                            "<Q", extra_data, ext_pos)[0]
                        ext_pos += 8
                    if local_header_offset == 0xFFFFFFFF and ext_pos + 8 <= ep + 4 + ext_size:
                        local_header_offset = struct.unpack_from(
                            "<Q", extra_data, ext_pos)[0]
                    break
                ep += 4 + ext_size

        total_parsed += 1
        if total_parsed % 25000 == 0:
            print(f"  Parsed {total_parsed} entries...")

        # Only keep MP3 files (skip directories)
        if name.endswith(".mp3") and not name.endswith("/"):
            entries.append(ZipEntry(
                name=name,
                compress_method=compress_method,
                compressed_size=compressed_size,
                uncompressed_size=uncompressed_size,
                local_header_offset=local_header_offset,
            ))

        pos += 46 + name_len + extra_len + comment_len

    print(f"Parsed {total_parsed} total entries, {len(entries)} MP3 files")
    return entries


def extract_and_upload(blob, bucket, entry: ZipEntry, prefix: str):
    """Extract a single file via range read and upload to GCS."""
    try:
        # Single range read: local header (30 bytes) + variable fields (up to 1KB)
        # + compressed data — all in one GCS API call
        HEADER_MARGIN = 1024  # covers variable-length name + extra fields
        read_start = entry.local_header_offset
        read_end = read_start + 30 + HEADER_MARGIN + entry.compressed_size
        buf = range_read(blob, read_start, read_end)

        if buf[:4] != LOCAL_HEADER_SIGNATURE:
            raise ValueError(f"Invalid local header for {entry.name}")

        local_name_len = struct.unpack_from("<H", buf, 26)[0]
        local_extra_len = struct.unpack_from("<H", buf, 28)[0]

        data_start = 30 + local_name_len + local_extra_len
        compressed_data = buf[data_start:data_start + entry.compressed_size]

        # Decompress
        if entry.compress_method == 0:
            # Stored (no compression)
            file_data = compressed_data
        elif entry.compress_method == 8:
            # Deflate
            file_data = zlib.decompress(compressed_data, -zlib.MAX_WBITS)
        elif entry.compress_method == 12:
            # Bzip2
            file_data = bz2.decompress(compressed_data)
        else:
            raise ValueError(f"Unsupported compression method "
                             f"{entry.compress_method} for {entry.name}")

        # Upload to GCS
        blob_path = f"{prefix}{entry.name}" if prefix else entry.name
        dest_blob = bucket.blob(blob_path)
        dest_blob.upload_from_string(file_data, content_type="audio/mpeg")

        stats["uploaded"] += 1
        if stats["uploaded"] % 100 == 0:
            print(f"Progress: uploaded={stats['uploaded']}/{stats['pending']}, "
                  f"errors={stats['errors']}")

    except Exception as e:
        print(f"Error extracting {entry.name}: {e}")
        stats["errors"] += 1


def list_existing_files(bucket, prefix: str) -> set:
    """List all existing files in the bucket prefix."""
    print(f"Listing existing files in gs://{bucket.name}/{prefix}...")
    existing = set()
    count = 0
    for blob in bucket.list_blobs(prefix=prefix):
        existing.add(blob.name)
        count += 1
        if count % 10000 == 0:
            print(f"  Listed {count} files...")
    print(f"Found {len(existing)} existing files")
    return existing


def main():
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)

    print(f"FMA Extraction: gs://{BUCKET_NAME}/{ZIP_BLOB} -> gs://{BUCKET_NAME}/{PREFIX}")
    print(f"Workers: {MAX_WORKERS}")

    # Check zip exists and get size
    zip_blob = bucket.blob(ZIP_BLOB)
    if not zip_blob.exists():
        print(f"ERROR: Zip file not found at gs://{BUCKET_NAME}/{ZIP_BLOB}")
        print("Run download_to_gcs.sh first to transfer the zip from Switzerland.")
        return

    zip_blob.reload()
    zip_size = zip_blob.size
    if not zip_size:
        print("ERROR: Could not determine zip file size")
        return
    print(f"Zip file size: {zip_size / 1e9:.1f} GB ({zip_size} bytes)")

    # Phase 1: Read central directory
    print("\n=== Phase 1: Reading ZIP central directory ===")
    cd_offset, cd_size, total_entries = find_eocd(zip_blob, zip_size)
    entries = parse_central_directory(zip_blob, cd_offset, cd_size)

    # Phase 2: Find already-extracted files
    print("\n=== Phase 2: Checking existing files ===")
    existing = list_existing_files(bucket, PREFIX)

    # Phase 3: Filter to pending
    pending = []
    for entry in entries:
        blob_path = f"{PREFIX}{entry.name}" if PREFIX else entry.name
        if blob_path not in existing:
            pending.append(entry)

    stats["skipped"] = len(entries) - len(pending)
    stats["pending"] = len(pending)

    print(f"\nTotal MP3s in zip: {len(entries)}")
    print(f"Already extracted: {stats['skipped']}")
    print(f"Pending extraction: {stats['pending']}")

    if not pending:
        print("\nAll files already extracted! Nothing to do.")
        return

    # Phase 4: Extract in parallel
    print(f"\n=== Phase 3: Extracting {len(pending)} files with {MAX_WORKERS} workers ===")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Process in batches to bound memory usage
        batch_size = MAX_WORKERS * 2
        for i in range(0, len(pending), batch_size):
            batch = pending[i:i + batch_size]
            futures = {
                executor.submit(extract_and_upload, zip_blob, bucket,
                                entry, PREFIX): entry
                for entry in batch
            }

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    entry = futures[future]
                    print(f"Unexpected error for {entry.name}: {e}")
                    stats["errors"] += 1

    print(f"\nComplete! uploaded={stats['uploaded']}, "
          f"skipped={stats['skipped']}, errors={stats['errors']}")


if __name__ == "__main__":
    main()
