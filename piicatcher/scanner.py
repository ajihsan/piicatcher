"""Different types of scanners for PII data"""
import logging
import re
from typing import Generator, List, Optional, Tuple

import crim as CommonRegex
from dbcat.catalog import Catalog
from dbcat.catalog.models import CatColumn, CatSchema, CatTable
from dbcat.catalog.pii_types import PiiType
from tqdm import tqdm

from piicatcher import (
    SSN,
    Address,
    BirthDate,
    CreditCard,
    Email,
    Gender,
    Nationality,
    Password,
    Person,
    Phone,
    PoBox,
    UserName,
    ZipCode,
    KTP,
)
from piicatcher.detectors import DatumDetector, MetadataDetector, register_detector
from piicatcher.generators import SMALL_TABLE_MAX, _filter_text_columns

LOGGER = logging.getLogger(__name__)


data_logger = logging.getLogger("piicatcher.data")
data_logger.propagate = False
data_logger.setLevel(logging.INFO)
data_logger.addHandler(logging.NullHandler())

scan_logger = logging.getLogger("piicatcher.scan")
scan_logger.propagate = False
scan_logger.setLevel(logging.INFO)
scan_logger.addHandler(logging.NullHandler())


@register_detector
class ColumnNameRegexDetector(MetadataDetector):
    regex = {
        Person: re.compile(
            "^.*(firstname|fname|lastname|lname|"
            "fullname|maidenname|_name|"
            "nickname|name_suffix|name|person|nama|nama_lengkap|nama_panjang).*$",
            re.IGNORECASE,
        ),
        Email: re.compile("^.*(email|e-mail|mail).*$", re.IGNORECASE),
        BirthDate: re.compile(
            "^.*(date_of_birth|dateofbirth|dob|"
            "birthday|date_of_death|dateofdeath|birthdate|tanggal_lahir).*$",
            re.IGNORECASE,
        ),
        Gender: re.compile("^.*(gender|jenis_kelamin).*$", re.IGNORECASE),
        Nationality: re.compile("^.*(nationality).*$", re.IGNORECASE),
        Address: re.compile(
            "^.*(address|city|state|county|country|zone|borough|"
            "alamat|provinsi|kota|kabupaten|kecamatan|kelurahan|desa|nomor_rumah).*$",
            re.IGNORECASE,
        ),
        ZipCode: re.compile(
            "^.*(zipcode|zip_code|postal|postal_code|zip|kode_pos|pos).*$",
            re.IGNORECASE,
        ),
        UserName: re.compile("^.*user(id|name|).*$", re.IGNORECASE),
        Password: re.compile("^.*pass.*$", re.IGNORECASE),
        SSN: re.compile(
            "^.*(ssn|social_number|social_security|"
            "social_security_number|social_security_no).*$",
            re.IGNORECASE,
        ),
        PoBox: re.compile("^.*(po_box|pobox).*$", re.IGNORECASE),
        CreditCard: re.compile(
            "^.*(credit_card|cc_number|cc_num|creditcard|"
            "credit_card_num|creditcardnumber|kartu_kredit|nomor_rekening|rekening).*$",
            re.IGNORECASE,
        ),
        Phone: re.compile(
            "^.*(phone|phone_number|phone_no|phone_num|"
            "telephone|telephone_num|telephone_no|telp|nomor_telepon|nomor_handphone|handphone|telepon|no_telepon|no_handphone).*$",
            re.IGNORECASE,
        ),
        KTP: re.compile(
            "^.*(ktp|ktp_name|ktp_number|nama_ktp|"
            "nomor_ktp|ktp_nama|ktp_nomor|ktp_no).*$",
            re.IGNORECASE,
        ),
    }

    name = "ColumnNameRegexDetector"

    def detect(self, column: CatColumn) -> Optional[PiiType]:
        for pii_type, ex in self.regex.items():
            if ex.match(column.name) is not None:
                return pii_type()

        return None


def metadata_scan(
    catalog: Catalog,
    detectors: List[MetadataDetector],
    work_generator: Generator[Tuple[CatSchema, CatTable, CatColumn], None, None],
    generator: Generator[Tuple[CatSchema, CatTable, CatColumn], None, None],
):
    total_columns = len([c for s, t, c in work_generator])
    counter = 0
    set_number = 0
    for schema, table, column in tqdm(
        generator, total=total_columns, desc="columns", unit="columns"
    ):
        counter += 1
        LOGGER.debug("Scanning column name %s", column.fqdn)
        for detector in detectors:
            type = detector.detect(column)
            if type is not None:
                set_number += 1
                catalog.set_column_pii_type(
                    column=column, pii_type=type, pii_plugin=detector.name
                )
                break

    LOGGER.info("Columns Scanned: %d, Columns Labeled: %d", counter, set_number)


@register_detector
class DatumRegexDetector(DatumDetector):
    """A scanner that uses common regular expressions to find PII"""

    name = "DatumRegexDetector"

    def detect(self, column: CatColumn, datum: str) -> Optional[PiiType]:
        """Scan the text and return an array of PiiTypes that are found"""
        data = str(datum)

        if CommonRegex.phones(data):  # pylint: disable=no-member
            return Phone()
        if CommonRegex.emails(data):  # pylint: disable=no-member
            return Email()
        if CommonRegex.credit_cards(data):  # pylint: disable=no-member
            return CreditCard()
        if CommonRegex.street_addresses(data):  # pylint: disable=no-member
            return Address()
        if CommonRegex.ssn_numbers(data):  # pylint: disable=no-member
            return SSN()
        if CommonRegex.zip_codes(data):  # pylint: disable=no-member
            return ZipCode()
        if CommonRegex.po_boxes(data):  # pylint: disable=no-member
            return PoBox()
        if CommonRegex.ktp(data):  # pylint: disable=no-member
            return KTP()

        return None


def data_scan(
    catalog: Catalog,
    detectors: List[DatumDetector],
    work_generator: Generator[Tuple[CatSchema, CatTable, CatColumn], None, None],
    generator: Generator[Tuple[CatSchema, CatTable, CatColumn, str], None, None],
    sample_size: int = SMALL_TABLE_MAX,
):
    total_columns = _filter_text_columns([c for s, t, c in work_generator])
    total_work = len(total_columns) * sample_size

    counter = 0
    set_number = 0

    for schema, table, column, val in tqdm(
        generator, total=total_work, desc="datum", unit="datum"
    ):
        counter += 1
        LOGGER.debug("Scanning column name %s", column.fqdn)
        if val is not None:
            for detector in detectors:
                type = detector.detect(column=column, datum=val)
                if type is not None:
                    set_number += 1

                    catalog.set_column_pii_type(
                        column=column, pii_type=type, pii_plugin=detector.name
                    )
                    LOGGER.debug("{} has {}".format(column.fqdn, type))

                    scan_logger.info(
                        "deep_scan", extra={"column": column.fqdn, "pii_types": type}
                    )
                    data_logger.info(
                        "deep_scan",
                        extra={"column": column.fqdn, "data": val, "pii_types": type},
                    )
                    break
    LOGGER.info("Columns Scanned: %d, Columns Labeled: %d", counter, set_number)
