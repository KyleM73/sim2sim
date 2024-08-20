import numpy as np

import pybullet as p
import pybullet_utils.bullet_client as bc
import pybullet_data
import time

from utils import dict_to_list, list_to_list


class CommandGenerator:
    def __init__(self, init_cmd: list = [0, 0, 0]) -> None:
        # [vy, vy, yaw_rate]
        self.vel_cmd = init_cmd

    def __call__(self) -> list:
        return self.vel_cmd


class Env:
    def __init__(self) -> None:
        # Get PyBullet client
        self.client = bc.BulletClient(connection_mode=p.GUI)
        self.client.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)

        # Initiate simulation
        self.client.resetSimulation()
        self.client.setPhysicsEngineParameter(enableConeFriction=0)
        self.client.setAdditionalSearchPath(pybullet_data.getDataPath())

        # Set up simulation
        self.sim_f = 200
        self.sim_dt = 1. / self.sim_f
        self.control_f = 50
        self.control_dt = 1. / self.control_f
        self.repeat = int(self.sim_f / self.control_f)
        self.client.setTimeStep(self.sim_dt)
        self.gravity = [0, 0, -9.81]
        self.client.setGravity(*self.gravity)

        # Set up command generator
        self.command_generator = CommandGenerator([0, 0, 0])

        # Set up ground
        self.ground = self.client.loadURDF("plane.urdf")
        self.client.changeDynamics(
            self.ground, -1,
            lateralFriction=1, rollingFriction=1
        )

        # Set up robot
        self.Kp, self.Kd, self.Ka = 0.1, 0.0001, 0.25
        self.tau_lim = 50
        init_pose = [0.0, 0.0, 0.4]
        init_ori = p.getQuaternionFromEuler([0.0, 0.0, 0.0])
        flags = p.URDF_MERGE_FIXED_LINKS \
            | p.URDF_USE_SELF_COLLISION  # \
        #   | p.URDF_USE_SELF_COLLISION_EXCLUDE_ALL_PARENTS
        self.robot = self.client.loadURDF(
            "robots/go1/go1.urdf", init_pose, init_ori, flags=flags
        )
        self.joints = {}
        self.links = {}
        for j in range(self.client.getNumJoints(self.robot)):
            self.client.enableJointForceTorqueSensor(
                self.robot, j, 1
            )
            self.client.changeDynamics(
                self.robot, j, linearDamping=0, angularDamping=0,
                lateralFriction=0.8, rollingFriction=0.6
            )
            info = self.client.getJointInfo(self.robot, j)
            joint_name = info[1].decode("utf8")
            joint_type = info[2]
            if (joint_type in [p.JOINT_PRISMATIC, p.JOINT_REVOLUTE]):
                self.joints[joint_name] = j
                self.links[joint_name.split("_joint")[0]] = j
        info = self.client.getDynamicsInfo(self.robot, -1)
        self.client.changeDynamics(
            self.robot, -1, linearDamping=0, angularDamping=0,
            lateralFriction=0.8, rollingFriction=0.6,
        )
        self.links["trunk"] = -1

        self.joints_isaac = {
            "FR_hip_joint": 1,
            "FL_hip_joint": 0,
            "RR_hip_joint": 3,
            "RL_hip_joint": 2,
            "FR_thigh_joint": 5,
            "FL_thigh_joint": 4,
            "RR_thigh_joint": 7,
            "RL_thigh_joint": 6,
            "FR_calf_joint": 9,
            "FL_calf_joint": 8,
            "RR_calf_joint": 11,
            "RL_calf_joint": 10,
        }

        self.q_init = {
            "FR_hip_joint": -0.1,
            "FL_hip_joint": 0.1,
            "RR_hip_joint": -0.1,
            "RL_hip_joint": 0.1,
            "FR_thigh_joint": 0.8,
            "FL_thigh_joint": 0.8,
            "RR_thigh_joint": 1.0,
            "RL_thigh_joint": 1.0,
            "FR_calf_joint": -1.5,
            "FL_calf_joint": -1.5,
            "RR_calf_joint": -1.5,
            "RL_calf_joint": -1.5,
        }
        self.q_init_arr = np.array(dict_to_list(self.q_init, self.joints))
        self.dq_init_arr = np.array([0 for _ in range(12)])
        self.tau_lim_arr = np.array([self.tau_lim for _ in range(12)])
        self.Kp_arr = [self.Kp] * 12
        self.Kd_arr = [self.Kd] * 12

        for j in range(12):
            self.client.resetJointState(
                self.robot, j, self.q_init_arr[j]
            )

        print("Robot init...")
        for _ in range(5 * self.control_f * self.repeat):
            # PD Mode
            self.client.setJointMotorControlArray(
                self.robot,
                [j for j in range(self.client.getNumJoints(self.robot))],
                p.POSITION_CONTROL,
                targetPositions=self.q_init_arr,
                targetVelocities=self.dq_init_arr,
                forces=self.tau_lim_arr,
                positionGains=self.Kp_arr,
                velocityGains=self.Kd_arr,
            )
            # Torque Mode
            """states = self.client.getJointStates(
                self.robot,
                [j for j in range(self.client.getNumJoints(self.robot))]
            )
            q, dq = [], []
            for state in states:
                q.append(state[0])
                dq.append(state[1])
            q_err = np.array(q) - self.q_init_arr
            dq_err = np.array(dq)
            self.client.setJointMotorControlArray(
                self.robot,
                [j for j in range(self.client.getNumJoints(self.robot))],
                p.TORQUE_CONTROL,
                forces=self.Kp * q_err + self.Kd * dq_err,
            )"""
            self.client.stepSimulation()
            time.sleep(self.sim_dt)

        print("Policy start:")

    def step(self, action) -> list:
        # Convert Isaac to PyBullet Ordering
        action = np.array(list_to_list(action, self.joints_isaac, self.joints))
        for _ in range(self.repeat):
            # PD Mode
            self.client.setJointMotorControlArray(
                self.robot,
                [j for j in range(self.client.getNumJoints(self.robot))],
                p.POSITION_CONTROL,
                targetPositions=self.q_init_arr + self.Ka * action,
                targetVelocities=self.dq_init_arr,
                forces=self.tau_lim_arr,
                positionGains=self.Kp_arr,
                velocityGains=self.Kd_arr,
            )
            # Torque Mode
            """states = self.client.getJointStates(
                self.robot,
                [j for j in range(self.client.getNumJoints(self.robot))]
            )
            q, dq = [], []
            for state in states:
                q.append(state[0])
                dq.append(state[1])
            q_err = np.array(q) - (self.q_init_arr + self.Ka * action)
            dq_err = np.array(dq)
            self.client.setJointMotorControlArray(
                self.robot,
                [j for j in range(self.client.getNumJoints(self.robot))],
                p.TORQUE_CONTROL,
                forces=self.Kp * q_err + self.Kd * dq_err,
            )
            print("position error: ", q_err)
            print("velocity error: ", dq_err)
            print("torque: ", self.Kp * q_err + self.Kd * dq_err)"""
            self.client.stepSimulation()
            time.sleep(self.sim_dt)
        self.action = action.tolist()
        obs = self.get_obs()
        return obs

    def quat_rot_inv(self, quat_list: list, gravity: list) -> list:
        quat = np.array(quat_list)
        gravity = np.array(gravity)
        q_w = quat[3]
        q_vec = quat[:3]
        a = gravity * (2.0 * q_w**2 - 1.0)
        b = np.cross(q_vec, gravity) * q_w * 2.0
        c = q_vec * q_vec * gravity
        return (a - b + c).tolist()

    def get_obs(self) -> list:
        obs = []
        # Projected gravity
        _, ori = self.client.getBasePositionAndOrientation(self.robot)
        obs += self.quat_rot_inv(ori, self.gravity)
        # Velocity Command
        obs += self.command_generator()
        # Joint Pose and Velocity
        states = self.client.getJointStates(
            self.robot,
            [j for j in range(self.client.getNumJoints(self.robot))]
        )
        q, dq = [], []
        for state in states:
            q.append(state[0])
            dq.append(state[1])
        obs += list_to_list(q, self.joints, self.joints_isaac)
        obs += list_to_list(dq, self.joints, self.joints_isaac)
        # Last Action
        obs += list_to_list(self.action, self.joints, self.joints_isaac)
        return obs