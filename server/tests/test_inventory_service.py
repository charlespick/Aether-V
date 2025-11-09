"""
Tests for inventory service.
"""
from unittest.mock import Mock

import pytest

from app.services.inventory_service import InventoryService


@pytest.mark.unit
class TestInventoryService:
    """Test inventory service basic functionality."""

    def test_initialization(self):
        """Test inventory service initializes with empty state."""
        service = InventoryService()
        
        assert len(service.clusters) == 0
        assert len(service.hosts) == 0
        assert len(service.vms) == 0
        assert service.last_refresh is None

    def test_get_all_hosts_empty(self):
        """Test retrieving all hosts when empty."""
        service = InventoryService()
        
        all_hosts = service.get_all_hosts()
        assert len(all_hosts) == 0

    def test_get_all_vms_empty(self):
        """Test retrieving all VMs when empty."""
        service = InventoryService()
        
        all_vms = service.get_all_vms()
        assert len(all_vms) == 0

    def test_get_host_vms_empty(self):
        """Test retrieving VMs for a specific host when empty."""
        service = InventoryService()
        
        host_vms = service.get_host_vms("nonexistent-host")
        assert len(host_vms) == 0

    def test_get_vm_nonexistent(self):
        """Test retrieving a nonexistent VM returns None."""
        service = InventoryService()
        
        vm = service.get_vm("nonexistent-host", "nonexistent-vm")
        assert vm is None

    def test_get_metrics(self):
        """Test getting metrics from empty service."""
        service = InventoryService()
        
        metrics = service.get_metrics()
        assert isinstance(metrics, dict)
        assert "clusters_tracked" in metrics
        assert metrics["clusters_tracked"] == 0

