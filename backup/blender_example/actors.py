from bge_network import Actor, PlayerController, InputManager, PhysicsData, Physics, AttatchmentSocket
from network import WorldInfo, StaticValue, Attribute, RPC, Netmodes, Roles, reliable, simulated, NetmodeOnly, Replicable

from bge import events, logic, render, constraints
from mathutils import Vector, Euler

from math import ceil

class Weapon(Actor):
    object_name = "Weapon"
    
    clip = Attribute(20)
    bullets = Attribute(100)
    roles = Attribute(
                      Roles(
                            local=Roles.authority, 
                            remote=Roles.simulated_proxy
                            )
                      )
    
    def on_registered(self):
        super().on_registered()
        
        # Hertz
        self.fire_rate = 20
        self.range = 10
        self.clip_size = 20
        self.round_damage = 2
        self.automatic = True
        self.sound = "//sounds/sfx_gunshot6.wav"
        self.last_fired_time = 0
        
        self.previous_owner = None
    
    def on_notify(self, name):
        if name == "owner":
            if self.previous_owner is not None:
                pass
    
    def play_effects(self):
        scene = self.scene
        scene.addObject('muzzle_flash_2', self, 15)
        scene.addObject('bullet_trail', self, 100)
        scene.addObject('small_sparks', self, 25)
    
    def conditions(self, is_owner, is_complaint, is_initial):
        yield from super().conditions(is_owner, is_complaint, is_initial)
        
        if is_complaint:
            yield "bullets"
            yield "clip"
    
    def fireable(self, timestamp):
        # Assume time validity check handled by movement
        return bool(self.clip) and (timestamp - self.last_fired_time) >= (1/self.fire_rate)
    
    def fired(self, timestamp):
        self.last_fired_time = timestamp
    
    def reload(self):
        needed_refill = self.clip_size - self.clip
        new_clip = min(self.bullets, needed_refill)
        self.bullets -= new_clip
        self.clip += new_clip
    
    def get_fired_bullets(self, deltatime):
        max_bullets = ceil(deltatime * self.fire_rate)
        fired_bullets = min(self.clip, max_bullets)
        return fired_bullets
    
    def fire(self, deltatime):
        fired_bullets = self.get_fired_bullets(deltatime)
        self.clip -= fired_bullets
        
        fire_range = self.range
        ray_cast = self.rayCast
        shoot_rule = WorldInfo.rules.on_shoot
        
        offset = 1.0
        y_axis = self.getAxisVect((0, 1, 0))
        origin = self.physics.position + y_axis * offset
        
        render.drawLine(origin, origin + y_axis*fire_range, [1,0,0])
        
        for shot in range(fired_bullets):
            hit_object, position, normal = ray_cast(origin + y_axis, origin, fire_range)
                
            if not hasattr(hit_object, "on_shot"):
                continue
            
            shoot_rule(hit_object, self.owner, self.round_damage)

class RPGInputs(InputManager):
    mappings = {"forward": events.WKEY, 
                "back": events.SKEY, 
                "shift": events.MKEY, 
                'right': events.DKEY, 
                'left': events.AKEY, 
                'shoot': events.LEFTMOUSE,
                'reload': events.RKEY,
                'jump': events.SPACEKEY,
                'simulate': events.XKEY}

class RPGController(PlayerController):
    
    input_class = RPGInputs
    
    def calculate_move(self, move):
        """Returns velocity and angular velocity of movement
        @param move: move to execute"""
        move_speed = 6.0 
        rotation_speed = 4.0
        
        inputs = move.inputs
        
        if not self.pawn.on_ground:
            return Vector(), Vector()
        
        if inputs.jump.pressed:
            self.pawn.character_controller.jump()
        
        # Get directional signs
        y_direction = (inputs.forward.active - inputs.back.active)
        x_direction = (inputs.left.active - inputs.right.active)
        
        # Get scaled vectors
        velocity = Vector((0.000, y_direction * move_speed, 0.000))
        angular = Vector((0.000, 0.000, x_direction * rotation_speed))
        
        # Make the velocity 
        velocity = self.pawn.local_to_global(velocity)
        return velocity, angular
            
    @RPC
    def server_perform_move(self, move_id: StaticValue(int, max_value=65535), timestamp: StaticValue(float), deltatime: StaticValue(float), inputs: StaticValue(InputManager), physics: StaticValue(PhysicsData)) -> Netmodes.server:
        allowed = self.check_delta_time(timestamp, deltatime)
        
        # This is also run on server but we need to ensure valid move for shooting
        if not allowed:
            print("Move delta time invalid")
            return
        
        # Get current pawn object that we control
        pawn = self.pawn

        # Perform weapon firing before physics
        if pawn.weapon:
            if inputs.reload.pressed:
                pawn.weapon.reload()
                
            if inputs.shoot.active and pawn.weapon.fireable(timestamp):
                pawn.weapon.fire(deltatime)
                pawn.weapon.fired(timestamp)
                print("FIRE")
        
        # Run default movement
        super().server_perform_move(move_id, timestamp, deltatime, inputs, physics)
            
    def player_update(self, delta_time):
        super().player_update(delta_time)
        
        # Make sure we have a pawn object
        pawn = self.pawn
        
        if not pawn:
            return
        
        timestamp = WorldInfo.elapsed
        
        inputs = self.player_input
        
        # Sound function
        hear_sound = self.client_hear_sound

        if inputs.simulate.pressed:
            self.server_correct()

        # Play fire effects if can shoot
        if inputs.shoot.active and pawn.weapon:
            
            if pawn.weapon.fireable(timestamp):
    
                fired_bullets = pawn.weapon.get_fired_bullets(delta_time)
                
                for i in range(fired_bullets):
                    pawn.weapon.play_effects()
                    hear_sound(pawn.weapon.sound, pawn.physics.position)
                    
                pawn.weapon.fired(timestamp)     
        
class LadderPoint(Actor):
    pass

class LadderBase(LadderPoint):
    object_name = "LadderBase"
    
class LadderTop(LadderPoint):
    object_name = "LadderTop"

class FloorMesh(Actor):
    object_name = "Plane"

class FloorCollider(Actor):
    object_name = "FloorCollider"
    
    roles = Attribute(
                      Roles(
                            Roles.authority, 
                            Roles.none
                            )
                      )
    
    def on_registered(self):
        super().on_registered()
        self.colliders = []
        
    @simulated 
    def on_new_collision(self, collider):
        self.colliders.append(collider)
    
    @simulated
    def on_end_collision(self, collider):
        self.colliders.remove(collider)

class Player(Actor):
    object_name = "Player"
    
    health = Attribute(100)
    
    weapon = Attribute(
                       type_of=Replicable, 
                       notify=True
                       )
    
    roles = Attribute(
                      Roles(
                            Roles.authority, 
                            Roles.autonomous_proxy
                            )
                      )
    physics = Attribute(
                        PhysicsData(
                                    mode=Physics.character, 
                                    position=Vector((0,0, 3))
                                    ),
                        notify=True
                        )
    
    def on_registered(self):
        super().on_registered()
        
        # Create a fixed attatchment point
        self.attatchment_point = AttatchmentSocket(self, Vector((0, 2, 0)))
        #self.floor_collider = FloorCollider()
        
        # Setup floor collider
        #self.floor_collider.physics.position = self.physics.position.copy()
        #self.floor_collider.physics.position.z -= 1.2
        #self.floor_collider.setParent(self)
        
        self.allowed_transitions = [LadderPoint, FloorMesh]
        
    def conditions(self, is_owner, is_complaint, is_initial):
        yield from super().conditions(is_owner, is_complaint, is_initial)
        
        if is_complaint:
            yield "weapon"
    
    def on_notify(self, name):
        if name == "weapon":
            self.pickup_weapon(self.weapon)
        else:
            super().on_notify(name)
    
    def on_unregistered(self):        
        '''Ensure that the weapon remains in the world'''
        if self.weapon:
            self.weapon.physics.mode = Physics.rigidbody
            self.attatchment_point.detach()
            
        super().on_unregistered()
    
    @RPC
    def request_pickup_weapon(self, other: StaticValue(Replicable))->Netmodes.server:        
        if other.owner:
            self.drop_weapon(other)
        else:
            self.weapon = other
            self.pickup_weapon(other)
    
    def pickup_weapon(self, other):
        self.attatchment_point.attach(other, align=True)
    
    def on_new_collision(self, other):
        if isinstance(other, Weapon) and other != self.weapon:
            if WorldInfo.netmode != Netmodes.server:
                self.request_pickup_weapon(other)
                self.pickup_weapon(other)
                print("Pickup weapon", other)
    
    @property
    def on_ground(self):
        return 1
        #return any(not isinstance(a, type(self)) for a in self.floor_collider.colliders)
    
    def on_shot(self, shooter, damage):
        self.health -= damage
        print("shot by {}".format(shooter.name))
        
    