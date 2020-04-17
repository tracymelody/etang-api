import datetime
import shutil
from unittest.mock import ANY, MagicMock, patch

import pytest
import pytz
from django.core.files import File
from freezegun import freeze_time

from saleor.csv import JobStatus
from saleor.csv.models import Job
from saleor.csv.utils.export import (
    create_csv_file_and_save_in_job,
    export_products,
    get_filename,
    get_product_queryset,
    on_task_failure,
    on_task_success,
    save_csv_file_in_job,
    update_job_when_task_finished,
)


def test_on_task_failure(job):
    exc = Exception("Test")
    task_id = "task_id"
    args = [job.pk, {"all": ""}]
    kwargs = {}
    einfo = None

    assert job.status == JobStatus.PENDING
    assert job.created_at
    assert not job.completed_at

    on_task_failure(None, exc, task_id, args, kwargs, einfo)

    job.refresh_from_db()
    assert job.status == JobStatus.FAILED
    assert job.created_at
    assert job.completed_at


def test_on_task_success(job):
    task_id = "task_id"
    args = [job.pk, {"filter": {}}]
    kwargs = {}

    assert job.status == JobStatus.PENDING
    assert job.created_at
    assert not job.completed_at

    on_task_success(None, None, task_id, args, kwargs)

    job.refresh_from_db()
    assert job.status == JobStatus.SUCCESS
    assert job.created_at
    assert job.completed_at


def test_update_job_when_task_finished(job):
    with freeze_time(datetime.datetime.now()) as frozen_datetime:
        assert not job.completed_at
        update_job_when_task_finished(job.pk, JobStatus.FAILED)

        job.refresh_from_db()
        assert job.completed_at == pytz.utc.localize(frozen_datetime())


@pytest.mark.parametrize("scope", [{"filter": {"is_published": True}}, {"all": ""}])
@patch("saleor.csv.utils.export.send_email_with_link_to_download_csv")
@patch("saleor.csv.utils.export.save_csv_file_in_job")
def test_export_products(
    save_csv_file_in_job_mock, send_email_mock, product_list, job, scope
):
    export_products(job.id, scope)

    save_csv_file_in_job_mock.called_once_with(job, ANY)
    send_email_mock.called_once_with(job)


@patch("saleor.csv.utils.export.send_email_with_link_to_download_csv")
@patch("saleor.csv.utils.export.save_csv_file_in_job")
def test_export_products_ids(
    save_csv_file_in_job_mock, send_email_mock, product_list, job
):
    pks = [product.pk for product in product_list[:2]]

    assert job.status == JobStatus.PENDING
    assert not job.completed_at
    assert not job.content_file

    export_products(job.id, {"ids": pks})

    save_csv_file_in_job_mock.called_once_with(job, ANY)
    send_email_mock.called_once_with(job)


def test_get_filename():
    with freeze_time("2000-02-09"):
        file_name = get_filename("test")

        assert file_name == "test_data_09_02_2000.csv"


def test_get_product_queryset_all(product_list):
    queryset = get_product_queryset({"all": ""})

    assert queryset.count() == len(product_list)


def test_get_product_queryset_ids(product_list):
    pks = [product.pk for product in product_list[:2]]
    queryset = get_product_queryset({"ids": pks})

    assert queryset.count() == len(pks)


def get_product_queryset_filter(product_list):
    product_not_published = product_list.first()
    product_not_published.is_published = False
    product_not_published.save()

    queryset = get_product_queryset({"ids": {"is_published": True}})

    assert queryset.count() == len(product_list) - 1


def test_create_csv_file_and_save_in_job(job, tmpdir):
    from django.conf import settings

    settings.MEDIA_ROOT = tmpdir

    export_data = [
        {"id": "123", "name": "test1", "collections": "coll1"},
        {"id": "345", "name": "test2"},
    ]
    headers = ["id", "name", "collections"]
    csv_headers_mapping = {"id": "ID", "name": "NAME"}
    delimiter = ";"
    job = job
    file_name = "test.csv"

    job_csv_upload_dir = Job.content_file.field.upload_to

    assert not job.content_file

    create_csv_file_and_save_in_job(
        export_data, headers, csv_headers_mapping, delimiter, job, file_name
    )

    csv_file = job.content_file
    assert csv_file
    assert csv_file.name == f"{job_csv_upload_dir}/{file_name}"

    file_content = csv_file.read().decode().split("\r\n")
    headers = list(csv_headers_mapping.values())
    headers.append("collections")

    assert ";".join(headers) in file_content
    assert ";".join(export_data[0].values()) in file_content
    assert (";".join(export_data[1].values()) + "; ") in file_content

    shutil.rmtree(tmpdir)


def test_save_csv_file_in_job(job, tmpdir):
    from django.conf import settings

    settings.MEDIA_ROOT = tmpdir

    file_mock = MagicMock(spec=File)
    file_mock.name = "temp_file.csv"
    file_name = "test.csv"

    assert not job.content_file

    save_csv_file_in_job(job, file_mock, file_name)

    job.refresh_from_db()
    assert job.content_file

    shutil.rmtree(tmpdir)