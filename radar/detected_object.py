# detected_object.py

class DetectedObject:
    def __init__(self, obj_id, position, velocity):
        """
        Initialize a detected object with ID, position, and velocity.

        :param obj_id: Unique identifier for the object.
        :param position: Tuple representing the (x, y) position.
        :param velocity: Tuple representing the (vx, vy) velocity components.
        """
        self.id = obj_id
        self.position = position  # e.g., (x, y)
        self.velocity = velocity  # e.g., (vx, vy)

    @property
    def is_moving(self):
        """
        Determine if the object is moving based on its velocity magnitude.

        :return: Boolean indicating movement status.
        """
        velocity_magnitude = (self.velocity[0] ** 2 + self.velocity[1] ** 2) ** 0.5
        VELOCITY_THRESHOLD = 0.5  # Adjust based on your radar's sensitivity
        return velocity_magnitude >= VELOCITY_THRESHOLD

    def __repr__(self):
        return f"DetectedObject(id={self.id}, position={self.position}, velocity={self.velocity})"
