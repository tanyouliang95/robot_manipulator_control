#!/usr/bin/env python

"""
=========================================================
Creator: Tan You Liang
Date: Sept 2018
Description:  Arm control process
              Edit `motion_config`.yaml for motion control
Gripper:      Open: 0, close: 1
==========================================================
"""


import sys
import os 
import copy
import rospy
import yaml
from time import sleep
from termcolor import colored

import moveit_commander
import moveit_msgs.msg
from moveit_commander.conversions import pose_to_list
import geometry_msgs.msg
import tf
from arm_manipulation import ArmManipulation

from math import pi
from std_msgs.msg import String
from std_msgs.msg import Int32
from std_msgs.msg import Float32MultiArray # temp solution
# from dynamixel_gripper.msg  import grip_state
from rm_msgs.msg import grip_state
from rm_msgs.msg import ManipulatorState


class RobotManipulatorControl():
  def __init__(self):

    rospy.init_node('robot_manipulator_control_node', anonymous=True)
    rospy.Subscriber("gripper/state", grip_state, self.gripperState_callback)
    self.gripper_pub = rospy.Publisher('gripper/command', Int32, queue_size=10)
    self.ur10 = ArmManipulation()   ## moveGroup  
    self.gripper_state = -1
    self.arm_motion_state = ''
    self.rate = rospy.Rate(6) # 6hz
    self.enable_gripper = False
    self.yaml_obj = []
    self.new_motion_request = False 
    self.motion_request = 'Nan' 
    self.motion_group_progress = -1.0


  def gripperState_callback(self, data): 
    # rospy.loginfo( "I heard gripper state is {}".format(data.gripper_state))
    self.gripper_state = data.gripper_state


  def motionService_callback(self, data): 
    self.motion_request = data.data 
    self.new_motion_request = True 


  # Open gripper, TODO: return success or fail
  def open_gripper(self): 

    if (self.enable_gripper == True):
      gripper_command = 0       # command to open gripper
      rospy.loginfo(gripper_command) #printout
      self.gripper_pub.publish(gripper_command)

      # wait until get state is open
      while (self.gripper_state == 1):
        if (self.gripper_state == -1):
          print("Error From Gripper!!")
          return False  
        print("gripper still close... with state {}".format(self.gripper_state))
        self.rate.sleep()
    
    return True


  # Close Gripper, TODO: return success or fail
  def close_gripper(self):

    if (self.enable_gripper == True):
      gripper_command = 1       #command to close gripper
      rospy.loginfo(gripper_command)
      self.gripper_pub.publish(gripper_command)

      # wait until get state is close
      while (self.gripper_state == 0):
        if (self.gripper_state == -1):
          print("Error From Gripper!!")
          return False  
        print("gripper still open... with state {} ".format(self.gripper_state))
        self.rate.sleep()

    return True


  # Read Yaml file
  def load_motion_config(self,path):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    full_path = dir_path + "/" + path
    with open(full_path, 'r') as stream:
      try:
        self.yaml_obj = yaml.load(stream)
      except yaml.YAMLError as exc:
        print("Error in loading Yaml" + exc)
        exit(0)

    self.enable_gripper =  self.yaml_obj['enable_gripper'] # bool
  

  # Manage cartesian motion sequence from .yaml 
  def manage_cartesian_motion_list(self, cartesian_motion):
    motion_list = []

    for cartesian_id in cartesian_motion:
      # Support cooficient handling
      char_idx = cartesian_id.find('C')
      filtered_cartesian_id = cartesian_id[char_idx:len(cartesian_id)]
      coefficient = cartesian_id[0:char_idx]
      cartesian_data = self.yaml_obj['cartesian_motion'][filtered_cartesian_id]
      
      if (len(coefficient)> 0 ): # check if theres cooficient infront of Cartesian motion
        if (coefficient == '-'):
          coefficient = -1
        else:
          coefficient = float(coefficient)
        cartesian_data = map(lambda x: x *coefficient, cartesian_data)
      
      motion_list.append(cartesian_data)

    return motion_list


  """ 
  Execute single 'motion' according to 'motion_config.yaml' 
  @Input: String, motion_id 
  @Return: Bool, Success? 
  """
  def execute_motion(self, motion_id):
    try:
      motion_descriptor = self.yaml_obj['motion'][motion_id]
      motion_type = motion_descriptor['type']
      is_success = False
      print( colored(" -- Motion: {} ".format(motion_descriptor), 'blue') )

      ## **Joint Motion
      if ( motion_type == 'joint_goal'):
        joint_goal = motion_descriptor['data']
        motion_time_factor = motion_descriptor['timeFactor']
        is_success = self.ur10.go_to_joint_state(joint_goal, motion_time_factor)
        
      ## **Pose Goal Motion
      elif ( motion_type == 'pose_goal'):
        pose_goal = motion_descriptor['data']
        motion_time_factor = motion_descriptor['timeFactor']
        is_success = self.ur10.go_to_pose_goal(pose_goal, motion_time_factor)

      ## **Cartesian Motion
      elif ( motion_type == 'cartesian'):
        motion_time_factor = motion_descriptor['timeFactor']
        motion_sequence = motion_descriptor['sequence']
        cartesian_motion_list = self.manage_cartesian_motion_list( motion_sequence )

        cartesian_plan, planned_fraction = self.ur10.plan_cartesian_path(cartesian_motion_list, motion_time_factor)
        print(" -- Planned fraction: {} ".format(planned_fraction))
        if (planned_fraction == 1.0):
          is_success = self.ur10.execute_plan(cartesian_plan)

      ## **Close Gripper Motion
      elif ( motion_type == 'eef_grip_obj'):
        self.ur10.add_box()
        self.ur10.attach_box()
        is_success = self.close_gripper()

      ## **Open Gripper Motion
      elif ( motion_type == 'eef_release_obj'):
        self.ur10.detach_box()
        self.ur10.remove_box()
        is_success = self.open_gripper()
                
      else:
        print(colored("Error!! Invalid motion type in motion descriptor, motion_config.yaml", 'red', 'on_white'))
        exit(0)

      print(colored(" -- Motion success outcome: {}".format(is_success), 'green'))
    
    except KeyError, e:
      print(colored("ERROR!!! invalid key in dict of .yaml, pls check your input related to motion_config.yaml",'red'))  
    except IndexError, e:
      print(colored("ERROR!!! invalid index in list of .yaml, pls check your input related to motion_config.yaml",'red'))  

    return is_success



  """ 
  @input: String, Target Motion Group ID
  @return: Bool, success? 
  """
  def execute_motion_group(self, target_id):
    
    try:
      all_motion_groups = self.yaml_obj['motion_group']
      numOfMotionGroup = len(all_motion_groups)
      self.motion_group_progress = 0
      for i in range(numOfMotionGroup):
        
        if ( all_motion_groups[i]['id'] == target_id):  # if found id
          motion_sequences = all_motion_groups[i]['sequence']
          # Loop thru each 'motion'
          fraction = 1.0/len(motion_sequences)
          for motion_id in motion_sequences:
            self.execute_motion(motion_id)
            self.motion_group_progress = self.motion_group_progress + fraction
            self.rate.sleep()
          return True
      
    except KeyError, e:
      print(colored("ERROR!!! invalid key in dict of .yaml, pls check your input related to motion_config.yaml",'red'))  
    except IndexError, e:
      print(colored("ERROR!!! invalid index in list of .yaml, pls check your input related to motion_config.yaml",'red'))  
    
    return False
    


  """ 
  Execute series of motion groups, motions, and cartesian motions
  - Motion Groups are executed sequencially. Press enter to continue
  """
  def execute_all_motion_group(self):

    try:

      # Loop thru each 'motion group'
      for obj, i in zip(self.yaml_obj['motion_group'], range(99)):
        motion_sequences = obj['sequence']
        print( colored(" =================== Motion_Group {}: {} =================== ".format(i, motion_sequences), 'blue', attrs=['bold']) )
        print( colored(" -- Press `Enter` to execute a movement -- ", 'cyan') )
        raw_input()

        # Loop thru each 'motion'
        for motion_id in motion_sequences:
          self.execute_motion(motion_id)

      print(colored(" ===================  Motion Completed!  ===================", 'green'))

    except rospy.ROSInterruptException:
      return
    except KeyboardInterrupt:
      return


  """
  Execute a service node to call a specific motion group
   @Sub: '/ur10/motion_group_id', input group num id
   @Pub: '/ur10/manipulator_state', current state of the manipulator
  """
  def execute_motion_group_service(self):
    rospy.Subscriber("/ur10/motion_group_id", String, self.motionService_callback)
    self.RMC_pub = rospy.Publisher("/ur10/manipulator_state", ManipulatorState, queue_size=10)
    self.rm_bridge_pub = rospy.Publisher("/ur10/rm_bridge_state", Float32MultiArray, queue_size=10) # Temp Solution for RMC Pub
    rospy.Timer(rospy.Duration(0.5), self.timer_pub_callback)
    print (colored(" ------ Running motion group service ------ ", 'green', attrs=['bold']))

    while(1):
      # check if new request by user
      if (self.new_motion_request == True):
        print (" [Service]:: New Motion Group Request!! : {} ".format(self.motion_request) )
        self.new_motion_request = False
        self.execute_motion_group( self.motion_request )

      self.rate.sleep()


  # Timer to pub Manipulator` State in every interval
  # *Note: when motion is executing, ros callback is being blocked
  def timer_pub_callback(self, event):

      eef_pose = self.ur10.get_eef_pose()
    
      print ('[CallBack] pub timer called at: ' + str(event.current_real))
      qua = [ eef_pose.orientation.x, eef_pose.orientation.y, eef_pose.orientation.z, eef_pose.orientation.w]
      (roll, pitch, yaw) = tf.transformations.euler_from_quaternion(qua)

      msg = ManipulatorState()
      msg.gripper_state = self.gripper_state
      msg.arm_motion_state = self.motion_request
      msg.arm_motion_progress = self.motion_group_progress   # float, show fraction of completion
      msg.x = eef_pose.position.x
      msg.y = eef_pose.position.y
      msg.z = eef_pose.position.z
      msg.roll = roll
      msg.pitch = pitch
      msg.yaw = yaw

      self.RMC_pub.publish(msg)

      # TODO: temp solution to pub to ros1_ros2_bridge
      msg = Float32MultiArray()

      motion_group_num = self.motion_request[1:] # convert: e.g. 'G23' to 23
      if (motion_group_num.isdigit()):
        motion_group_num = float(motion_group_num)
      else:
        motion_group_num = -1.0
      msg.data =  [ self.gripper_state, 
                    motion_group_num, 
                    self.motion_group_progress, 
                    eef_pose.position.x,
                    eef_pose.position.y,
                    eef_pose.position.z,
                    roll,
                    pitch,
                    yaw ]
      self.rm_bridge_pub.publish(msg)
              





############################################################################################
############################################################################################



if __name__ == '__main__':
  print(colored("  -------- Begin Python Moveit Script --------  " , 'white', 'on_green'))
  robot_manipulator_control = RobotManipulatorControl()
  robot_manipulator_control.load_motion_config( path="../config/motion_config.yaml" )
  # robot_manipulator_control.execute_all_motion_group()
  
  robot_manipulator_control.execute_motion_group_service()
  # robot_manipulator_control.execute_motion_group("G5")
  
