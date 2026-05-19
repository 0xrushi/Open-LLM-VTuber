import unittest
import math

class TestVrmAnimationLogic(unittest.TestCase):
    """
    Simulates the mathematical logic used in vrm-viewer.tsx 
    to ensure retargeting and sways are calculated correctly.
    """

    def test_hips_position_scaling(self):
        """Verifies that hips are scaled relative to restY and don't sink into floor."""
        # Setup: Mixamo rest height is ~100, VRM rest height is 0.92
        mixamo_y0 = 100.0
        vrm_rest_y = 0.92
        
        # New Formula: pos = restY + (y_mixamo - y0) * (restY / y0)
        scale = vrm_rest_y / mixamo_y0
        
        # Case: First frame (rest pose)
        result_rest = vrm_rest_y + (mixamo_y0 - mixamo_y0) * scale
        self.assertAlmostEqual(result_rest, 0.92)
        
        # Case: Bob up 10 units (10% of height)
        mixamo_up = 110.0
        result_up = vrm_rest_y + (mixamo_up - mixamo_y0) * scale
        # Should be 0.92 + 0.092 = 1.012
        self.assertAlmostEqual(result_up, 1.012)
        
        # Case: Crouch down 20 units (20% of height)
        mixamo_down = 80.0
        result_down = vrm_rest_y + (mixamo_down - mixamo_y0) * scale
        # Should be 0.92 - 0.184 = 0.736
        self.assertAlmostEqual(result_down, 0.736)

    def test_z_roll_stripping_logic(self):
        """Verifies that Z-roll stripping follows the current option semantics."""
        trunk_bones = ["Spine", "Chest", "UpperChest"]

        def is_stabilized(bone_name, disable_z_roll_flag):
            # Current runtime logic:
            # shouldStripTrunkZRoll = options?.disableZRollStripping === false
            # _euler = (isTrunkBone && shouldStripTrunkZRoll) ? new Euler() : null
            is_trunk = bone_name in trunk_bones
            return is_trunk and (disable_z_roll_flag is False)

        # Explicit stripping enabled
        self.assertTrue(is_stabilized("Spine", False))
        self.assertTrue(is_stabilized("Chest", False))

        # Default behavior / dance behavior (disable_z_roll_flag = True)
        self.assertFalse(is_stabilized("Spine", True))
        self.assertFalse(is_stabilized("UpperChest", True))

        # Legs are never part of trunk Z-roll stripping now
        self.assertFalse(is_stabilized("LeftUpperLeg", False))
        self.assertFalse(is_stabilized("RightUpperLeg", False))

        # Non-trunk bones
        self.assertFalse(is_stabilized("LeftHand", False))

    def test_additive_sway_logic(self):
        """Verifies that sway is additive and doesn't reset base animation."""
        # Initial rotation from a Mixamo animation frame
        initial_rot_x = 0.15
        
        # Procedural sway value
        sway_val = 0.05
        
        # Logic: bone.rotation.x += sway_val
        final_rot_x = initial_rot_x + sway_val
        
        self.assertEqual(final_rot_x, 0.20)
        
        # Ensure it's not absolute assignment (which would be final = 0.05)
        self.assertNotEqual(final_rot_x, sway_val)

    def test_dance_distribution_trunk_boost_without_hip_boost(self):
        """Dance should boost trunk bend while keeping hips/legs stable."""
        # Values from runtime dance playback defaults.
        hips_rotation_multiplier = 1.0
        hips_position_multiplier = 1.0
        trunk_bend_multiplier = 1.35

        # Representative source values.
        hips_rot_x = 0.30
        hips_rot_z = 0.20
        spine_rot_x = 0.25
        chest_rot_x = 0.18
        hip_pos_xz = 0.10
        leg_rot_x = 0.22

        # Hips/legs unchanged
        self.assertAlmostEqual(hips_rot_x * hips_rotation_multiplier, hips_rot_x)
        self.assertAlmostEqual(hips_rot_z * hips_rotation_multiplier, hips_rot_z)
        self.assertAlmostEqual(hip_pos_xz * hips_position_multiplier, hip_pos_xz)
        self.assertAlmostEqual(leg_rot_x, 0.22)

        # Trunk bend amplified
        self.assertAlmostEqual(spine_rot_x * trunk_bend_multiplier, 0.3375)
        self.assertAlmostEqual(chest_rot_x * trunk_bend_multiplier, 0.243)

if __name__ == '__main__':
    unittest.main()
