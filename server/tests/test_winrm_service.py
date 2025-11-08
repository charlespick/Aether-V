"""Unit tests for helpers in the WinRM service."""

from pypsrp.powershell import InformationRecord
from pypsrp.serializer import GenericComplexObject

from app.services.winrm_service import _PSRPStreamCursor


def test_stringify_prefers_complex_object_properties():
    obj = GenericComplexObject()
    obj.to_string = "System.Management.ManagementBaseObject"
    obj.adapted_properties = {
        "Name": "vm-01",
        "State": "Running",
    }
    obj.extended_properties = {"Notes": "Provisioned"}

    rendered = _PSRPStreamCursor._stringify(obj)

    assert rendered == "Name: vm-01\nState: Running\nNotes: Provisioned"


def test_stringify_handles_nested_complex_property_values():
    child = GenericComplexObject()
    child.to_string = "System.Management.ManagementBaseObject"
    child.adapted_properties = {"Status": "Healthy"}

    parent = GenericComplexObject()
    parent.to_string = "System.Management.ManagementBaseObject"
    parent.adapted_properties = {
        "Name": "vm-02",
        "Child": child,
        "Tags": ["compute", "lab"],
        "Metadata": {"owner": "ops"},
    }

    rendered = _PSRPStreamCursor._stringify(parent)

    assert rendered == (
        "Name: vm-02\n"
        "Child:\n"
        "  Status: Healthy\n"
        "Tags: compute, lab\n"
        "Metadata: owner=ops"
    )


def test_stringify_information_prefers_message_data_text():
    record = InformationRecord(message_data="Copy complete")

    rendered = _PSRPStreamCursor._stringify_information(record)

    assert rendered == "Copy complete"


def test_stringify_information_falls_back_to_complex_data():
    payload = GenericComplexObject()
    payload.to_string = "System.Object"
    payload.adapted_properties = {"Message": "Transferring"}

    record = InformationRecord(message_data=payload)

    rendered = _PSRPStreamCursor._stringify_information(record)

    assert rendered == "Message: Transferring"
