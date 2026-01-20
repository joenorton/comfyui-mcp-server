"""Tests for publish manager and path safety utilities

Run with pytest from project root:
    pytest tests/test_publish.py -v
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from managers.publish_manager import (
    PublishConfig,
    PublishManager,
    auto_generate_filename,
    canonicalize_path,
    detect_project_root,
    get_default_publish_root,
    get_publish_config_dir,
    get_publish_config_file,
    is_within,
    load_publish_config,
    save_publish_config,
    validate_comfyui_output_root,
    validate_manifest_key,
    validate_target_filename,
)


class TestPathSafety:
    """Tests for path safety utilities"""
    
    def test_canonicalize_path_absolute(self, tmp_path):
        """Test canonicalize_path with absolute path"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        
        result = canonicalize_path(test_file)
        assert isinstance(result, Path)
        assert result.is_absolute()
        assert result.exists()
    
    def test_canonicalize_path_relative(self, tmp_path):
        """Test canonicalize_path with relative path"""
        os.chdir(tmp_path)
        test_file = Path("test.txt")
        test_file.write_text("test")
        
        result = canonicalize_path(test_file)
        assert isinstance(result, Path)
        assert result.is_absolute()
        assert result.exists()
    
    def test_canonicalize_path_nonexistent(self):
        """Test canonicalize_path with nonexistent path raises ValueError"""
        with pytest.raises(ValueError):
            canonicalize_path("/nonexistent/path/that/does/not/exist")
    
    def test_canonicalize_path_nonexistent_optional(self, tmp_path):
        """Test canonicalize_path with nonexistent path and must_exist=False"""
        nonexistent = tmp_path / "nonexistent" / "file.txt"
        result = canonicalize_path(nonexistent, must_exist=False)
        assert isinstance(result, Path)
        assert result.is_absolute()
        # Path doesn't exist, but should still resolve
    
    def test_is_within_simple(self, tmp_path):
        """Test is_within with simple parent-child relationship"""
        parent = tmp_path / "parent"
        parent.mkdir()
        child = parent / "child.txt"
        child.write_text("test")
        
        assert is_within(child, parent) is True
        assert is_within(parent, child) is False
    
    def test_is_within_nested(self, tmp_path):
        """Test is_within with nested directories"""
        parent = tmp_path / "parent"
        parent.mkdir()
        nested = parent / "nested" / "deep"
        nested.mkdir(parents=True)
        child = nested / "file.txt"
        child.write_text("test")
        
        assert is_within(child, parent) is True
        assert is_within(nested, parent) is True
    
    def test_is_within_outside(self, tmp_path):
        """Test is_within returns False for paths outside parent"""
        parent = tmp_path / "parent"
        parent.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        child = outside / "file.txt"
        child.write_text("test")
        
        assert is_within(child, parent) is False
    
    def test_is_within_traversal_attempt(self, tmp_path):
        """Test is_within prevents path traversal"""
        parent = tmp_path / "parent"
        parent.mkdir()
        
        # Try to escape with ../
        traversal = tmp_path / "parent" / ".." / "outside"
        traversal.parent.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        child = outside / "file.txt"
        child.write_text("test")
        
        # After canonicalization, traversal should be resolved
        # and should not be within parent
        assert is_within(child, parent) is False
    
    def test_is_within_same_path(self, tmp_path):
        """Test is_within with same path"""
        path = tmp_path / "test"
        path.mkdir()
        
        # A path is considered within itself
        assert is_within(path, path) is True
    
    def test_is_within_nonexistent_child(self, tmp_path):
        """Test is_within with nonexistent child path"""
        parent = tmp_path / "parent"
        parent.mkdir()
        nonexistent = parent / "nonexistent.txt"
        
        # Should work with child_must_exist=False
        assert is_within(nonexistent, parent, child_must_exist=False) is True


class TestValidationFunctions:
    """Tests for validation functions"""
    
    def test_validate_target_filename_valid(self):
        """Test validate_target_filename with valid filenames"""
        assert validate_target_filename("hero.webp") is True
        assert validate_target_filename("test-image.png") is True
        assert validate_target_filename("logo_123.jpg") is True
        assert validate_target_filename("a.webp") is True  # Min length
        assert validate_target_filename("a" * 63 + ".webp") is True  # Max length
    
    def test_validate_target_filename_invalid(self):
        """Test validate_target_filename with invalid filenames"""
        assert validate_target_filename("Hero.webp") is False  # Uppercase
        assert validate_target_filename("test.webp") is False  # Starts with lowercase but...
        assert validate_target_filename("../test.webp") is False  # Path traversal
        assert validate_target_filename("test/path.webp") is False  # Slash
        assert validate_target_filename("test\\path.webp") is False  # Backslash
        assert validate_target_filename(".webp") is False  # No name
        assert validate_target_filename("test") is False  # No extension
        assert validate_target_filename("test.gif") is False  # Invalid extension
        assert validate_target_filename("a" * 64 + ".webp") is False  # Too long
    
    def test_validate_manifest_key_valid(self):
        """Test validate_manifest_key with valid keys"""
        assert validate_manifest_key("hero") is True
        assert validate_manifest_key("test-image") is True
        assert validate_manifest_key("logo_123") is True
        assert validate_manifest_key("a") is True  # Min length
        assert validate_manifest_key("a" * 63) is True  # Max length
    
    def test_validate_manifest_key_invalid(self):
        """Test validate_manifest_key with invalid keys"""
        assert validate_manifest_key("Hero") is False  # Uppercase
        assert validate_manifest_key("../test") is False  # Path traversal
        assert validate_manifest_key("test/path") is False  # Slash
        assert validate_manifest_key("") is False  # Empty
        assert validate_manifest_key("a" * 64) is False  # Too long
        assert validate_manifest_key("test.webp") is False  # Extension not allowed
    
    def test_auto_generate_filename(self):
        """Test auto_generate_filename"""
        asset_id = "0b3eacbc-25b0-497c-9d63-6d66d9e67387"
        filename = auto_generate_filename(asset_id)
        
        assert filename.startswith("asset_")
        assert filename.endswith(".webp")
        assert "0b3eacbc" in filename  # First 8 chars of asset_id


class TestProjectRootDetection:
    """Tests for project root detection"""
    
    def test_detect_project_root_with_git(self, tmp_path):
        """Test detect_project_root finds .git marker"""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()  # Create .git marker
        
        os.chdir(project_root)
        root, method = detect_project_root()
        
        assert root == project_root.resolve()
        assert method in ("cwd", "auto-detected")
    
    def test_detect_project_root_with_public(self, tmp_path):
        """Test detect_project_root finds public/ directory"""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "public").mkdir()
        
        os.chdir(project_root)
        root, method = detect_project_root()
        
        assert root == project_root.resolve()
        assert method == "cwd"


class TestPublishConfig:
    """Tests for PublishConfig"""
    
    def test_init_minimal(self, tmp_path):
        """Test PublishConfig with minimal config (auto-detection)"""
        with patch('managers.publish_manager.detect_project_root', return_value=(tmp_path, "cwd")):
            config = PublishConfig()
            
            assert config.project_root == tmp_path.resolve()
            assert config.publish_root.exists()
            assert config.comfyui_output_root is None or config.comfyui_output_root.exists()
    
    def test_init_with_project_root(self, tmp_path):
        """Test PublishConfig with explicit project_root"""
        config = PublishConfig(project_root=tmp_path)
        
        assert config.project_root == tmp_path.resolve()
        assert config.publish_root.exists()
    
    def test_init_with_publish_root(self, tmp_path):
        """Test PublishConfig with explicit publish_root"""
        publish_root = tmp_path / "custom" / "publish"
        config = PublishConfig(project_root=tmp_path, publish_root=publish_root)
        
        assert config.publish_root == publish_root.resolve()
        assert config.publish_root.exists()
    
    def test_get_default_publish_root(self, tmp_path):
        """Test get_default_publish_root"""
        # Test public/gen
        (tmp_path / "public").mkdir()
        result = get_default_publish_root(tmp_path)
        assert result == (tmp_path / "public" / "gen").resolve()
        assert result.exists()
        
        # Test static/gen fallback
        tmp_path2 = Path(tempfile.mkdtemp())
        (tmp_path2 / "static").mkdir()
        result2 = get_default_publish_root(tmp_path2)
        assert result2 == (tmp_path2 / "static" / "gen").resolve()
    
    def test_validate_comfyui_output_root(self, tmp_path):
        """Test validate_comfyui_output_root"""
        output_root = tmp_path / "output"
        output_root.mkdir()
        
        # Create ComfyUI pattern files
        (output_root / "ComfyUI_00001.png").write_text("test")
        
        assert validate_comfyui_output_root(output_root) is True
    
    def test_validate_comfyui_output_root_with_images(self, tmp_path):
        """Test validate_comfyui_output_root with image files"""
        output_root = tmp_path / "output"
        output_root.mkdir()
        
        # Create image files (lenient check)
        (output_root / "image1.png").write_text("test")
        (output_root / "image2.jpg").write_text("test")
        (output_root / "image3.webp").write_text("test")
        
        assert validate_comfyui_output_root(output_root) is True


class TestPersistentConfig:
    """Tests for persistent configuration"""
    
    def test_get_publish_config_dir(self):
        """Test get_publish_config_dir returns platform-specific path"""
        config_dir = get_publish_config_dir()
        assert isinstance(config_dir, Path)
        assert config_dir.is_absolute()
    
    def test_get_publish_config_file(self):
        """Test get_publish_config_file returns config file path"""
        config_file = get_publish_config_file()
        assert isinstance(config_file, Path)
        assert config_file.name == "publish_config.json"
        assert config_file.parent == get_publish_config_dir()
    
    def test_save_and_load_publish_config(self, tmp_path, monkeypatch):
        """Test save_publish_config and load_publish_config"""
        # Mock config directory to use tmp_path
        config_dir = tmp_path / "config"
        config_file = config_dir / "publish_config.json"
        
        monkeypatch.setattr('managers.publish_manager.get_publish_config_dir', lambda: config_dir)
        monkeypatch.setattr('managers.publish_manager.get_publish_config_file', lambda: config_file)
        
        # Save config
        config = {"comfyui_output_root": "/test/path"}
        success = save_publish_config(config)
        assert success is True
        assert config_file.exists()
        
        # Load config
        loaded = load_publish_config()
        assert loaded == config


class TestPublishManager:
    """Tests for PublishManager"""
    
    def test_resolve_source_path_simple(self, tmp_path):
        """Test resolve_source_path with simple path"""
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        
        source_file = output_root / "test.png"
        source_file.write_text("test")
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        result = manager.resolve_source_path(subfolder="", filename="test.png")
        assert result == source_file.resolve()
    
    def test_resolve_source_path_with_subfolder(self, tmp_path):
        """Test resolve_source_path with subfolder"""
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        subfolder = output_root / "subfolder"
        subfolder.mkdir()
        
        source_file = subfolder / "test.png"
        source_file.write_text("test")
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        result = manager.resolve_source_path(subfolder="subfolder", filename="test.png")
        assert result == source_file.resolve()
    
    def test_resolve_source_path_outside_root(self, tmp_path):
        """Test resolve_source_path rejects paths outside output root"""
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_file = outside / "test.png"
        outside_file.write_text("test")
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        # Try to access file outside root via traversal
        with pytest.raises(ValueError, match="outside ComfyUI output root"):
            manager.resolve_source_path(subfolder="../../outside", filename="test.png")
    
    def test_resolve_source_path_nonexistent(self, tmp_path):
        """Test resolve_source_path with nonexistent file"""
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        with pytest.raises(ValueError, match="does not exist"):
            manager.resolve_source_path(subfolder="", filename="nonexistent.png")
    
    def test_resolve_target_path(self, tmp_path):
        """Test resolve_target_path with target_filename"""
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish"
        )
        manager = PublishManager(config)
        
        result = manager.resolve_target_path("hero.webp")
        expected = (tmp_path / "publish" / "hero.webp").resolve()
        assert result == expected
    
    def test_resolve_target_path_nonexistent(self, tmp_path):
        """Test resolve_target_path works when target file doesn't exist yet"""
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish"
        )
        manager = PublishManager(config)
        
        # Target file doesn't exist yet - should still work
        result = manager.resolve_target_path("hero.webp")
        assert not result.exists()  # File doesn't exist yet
        assert result.name == "hero.webp"
        assert result.parent == config.publish_root.resolve()
    
    def test_resolve_target_path_invalid_filename(self, tmp_path):
        """Test resolve_target_path rejects invalid filenames"""
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish"
        )
        manager = PublishManager(config)
        
        with pytest.raises(ValueError, match="Invalid target_filename"):
            manager.resolve_target_path("../escape.webp")
    
    def test_copy_asset_simple(self, tmp_path):
        """Test copy_asset with simple copy"""
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        source_file = output_root / "test.png"
        source_file.write_text("test content")
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        source_path = manager.resolve_source_path("", "test.png")
        target_path = manager.resolve_target_path("test.png")
        
        result = manager.copy_asset(source_path, target_path, overwrite=True)
        
        assert target_path.exists()
        assert target_path.read_text() == "test content"
        assert result["dest_path"] == str(target_path)
        assert result["bytes_size"] > 0
    
    def test_copy_asset_no_overwrite(self, tmp_path):
        """Test copy_asset with overwrite=False"""
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        source_file = output_root / "test.png"
        source_file.write_text("test content")
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        source_path = manager.resolve_source_path("", "test.png")
        target_path = manager.resolve_target_path("test.png")
        
        # Create existing file
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text("existing")
        
        with pytest.raises(ValueError, match="overwrite=False"):
            manager.copy_asset(source_path, target_path, overwrite=False)
        
        # File should still have original content
        assert target_path.read_text() == "existing"
    
    @pytest.mark.skipif(not pytest.importorskip("PIL", reason="Pillow not available"), reason="Pillow required for compression")
    def test_copy_asset_with_compression(self, tmp_path):
        """Test copy_asset compresses images"""
        from PIL import Image
        
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        
        # Create a test image
        source_file = output_root / "test.png"
        img = Image.new("RGB", (512, 512), color="red")
        img.save(source_file, "PNG")
        original_size = source_file.stat().st_size
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        source_path = manager.resolve_source_path("", "test.png")
        target_path = manager.resolve_target_path("test.webp")
        
        # Copy with compression (max 100KB)
        result = manager.copy_asset(
            source_path, 
            target_path, 
            overwrite=True,
            format="webp",
            max_bytes=100_000
        )
        
        assert target_path.exists()
        assert target_path.suffix == ".webp"
        assert "compression_info" in result
        assert result["compression_info"]["compressed"] is True
        assert result["bytes_size"] <= 100_000
    
    def test_update_manifest(self, tmp_path):
        """Test update_manifest with simple key→filename"""
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish"
        )
        manager = PublishManager(config)
        
        manager.update_manifest("hero", "hero.webp")
        
        manifest_path = config.publish_root / "manifest.json"
        assert manifest_path.exists()
        
        with open(manifest_path) as f:
            manifest = json.load(f)
        
        assert manifest["hero"] == "hero.webp"
        assert isinstance(manifest["hero"], str)  # Not an array
    
    def test_update_manifest_multiple_keys(self, tmp_path):
        """Test update_manifest with multiple keys"""
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish"
        )
        manager = PublishManager(config)
        
        manager.update_manifest("hero", "hero.webp")
        manager.update_manifest("logo", "logo.png")
        
        manifest_path = config.publish_root / "manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)
        
        assert manifest["hero"] == "hero.webp"
        assert manifest["logo"] == "logo.png"
    
    def test_ensure_ready(self, tmp_path):
        """Test ensure_ready checks configuration"""
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        (output_root / "ComfyUI_00001.png").write_text("test")
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        is_ready, error_code, error_info = manager.ensure_ready()
        assert is_ready is True
        assert error_code is None
    
    def test_ensure_ready_missing_comfyui_root(self, tmp_path):
        """Test ensure_ready fails when ComfyUI root missing"""
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=None
        )
        manager = PublishManager(config)
        
        is_ready, error_code, error_info = manager.ensure_ready()
        assert is_ready is False
        assert error_code == "COMFYUI_OUTPUT_ROOT_NOT_FOUND"


class TestPublishIntegration:
    """Integration tests for full publish workflow"""
    
    def test_full_publish_workflow_demo_mode(self, tmp_path, asset_registry):
        """Test full publish workflow in demo mode"""
        # Setup ComfyUI output
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        source_file = output_root / "test.png"
        source_file.write_text("test image content")
        
        # Setup publish config
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        # Register asset
        asset_record = asset_registry.register_asset(
            filename="test.png",
            subfolder="",
            folder_type="output",
            workflow_id="generate_image",
            prompt_id="test_prompt_123",
            mime_type="image/png",
            width=512,
            height=512,
            bytes_size=len(source_file.read_text())
        )
        
        # Publish asset (demo mode)
        source_path = manager.resolve_source_path(
            subfolder=asset_record.subfolder,
            filename=asset_record.filename
        )
        target_path = manager.resolve_target_path("hero.webp")
        
        publish_info = manager.copy_asset(
            source_path=source_path,
            target_path=target_path,
            overwrite=True,
            asset_id=asset_record.asset_id,
            target_filename="hero.webp"
        )
        
        # Verify file was copied
        assert target_path.exists()
        assert target_path.read_text() == "test image content"
    
    def test_full_publish_workflow_library_mode(self, tmp_path, asset_registry):
        """Test full publish workflow in library mode with manifest"""
        # Setup ComfyUI output
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        source_file = output_root / "test.png"
        source_file.write_text("test image content")
        
        # Setup publish config
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        # Register asset
        asset_record = asset_registry.register_asset(
            filename="test.png",
            subfolder="",
            folder_type="output",
            workflow_id="generate_image",
            prompt_id="test_prompt_123",
            mime_type="image/png"
        )
        
        # Publish asset (library mode - auto-generate filename)
        source_path = manager.resolve_source_path(
            subfolder=asset_record.subfolder,
            filename=asset_record.filename
        )
        auto_filename = auto_generate_filename(asset_record.asset_id)
        target_path = manager.resolve_target_path(auto_filename)
        
        publish_info = manager.copy_asset(
            source_path=source_path,
            target_path=target_path,
            overwrite=True,
            asset_id=asset_record.asset_id,
            target_filename=auto_filename
        )
        
        # Update manifest
        manager.update_manifest("hero-image", target_path.name)
        
        # Verify manifest was updated
        manifest_path = config.publish_root / "manifest.json"
        assert manifest_path.exists()
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest["hero-image"] == target_path.name
    
    def test_publish_rejects_expired_asset(self, tmp_path, asset_registry):
        """Test that publishing rejects expired assets"""
        from datetime import datetime, timedelta
        
        # Register and immediately expire
        asset_record = asset_registry.register_asset(
            filename="test.png",
            subfolder="",
            folder_type="output",
            workflow_id="generate_image",
            prompt_id="test_prompt_123"
        )
        
        # Manually expire the asset
        asset_record.expires_at = datetime.now() - timedelta(hours=1)
        
        # Asset should not be found
        found = asset_registry.get_asset(asset_record.asset_id)
        assert found is None
    
    def test_publish_rejects_path_traversal(self, tmp_path):
        """Test that publishing rejects path traversal attempts"""
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        
        # Create file outside output root
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_file = outside / "malicious.png"
        outside_file.write_text("malicious")
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        # Try to access file outside root via traversal
        with pytest.raises(ValueError, match="outside ComfyUI output root"):
            manager.resolve_source_path(subfolder="../../outside", filename="malicious.png")
    
    def test_publish_log_append(self, tmp_path):
        """Test that publish log appends multiple entries"""
        output_root = tmp_path / "comfyui" / "output"
        output_root.mkdir(parents=True)
        source1 = output_root / "test1.png"
        source1.write_text("test1")
        source2 = output_root / "test2.png"
        source2.write_text("test2")
        
        config = PublishConfig(
            project_root=tmp_path,
            publish_root=tmp_path / "publish",
            comfyui_output_root=output_root
        )
        manager = PublishManager(config)
        
        # Publish first asset
        target1 = manager.resolve_target_path("test1.webp")
        manager.copy_asset(source1, target1, asset_id="asset1", target_filename="test1.webp")
        
        # Publish second asset
        target2 = manager.resolve_target_path("test2.webp")
        manager.copy_asset(source2, target2, asset_id="asset2", target_filename="test2.webp")
        
        # Verify log has both entries
        log_path = config.publish_root / "publish_log.jsonl"
        assert log_path.exists()
        
        with open(log_path) as f:
            lines = f.readlines()
        
        assert len(lines) == 2
        entry1 = json.loads(lines[0])
        entry2 = json.loads(lines[1])
        assert entry1["target_filename"] == "test1.webp"
        assert entry2["target_filename"] == "test2.webp"
