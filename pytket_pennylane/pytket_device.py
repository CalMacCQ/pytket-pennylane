#creating device class to build Pennylane plugin
import numpy as np
import pennylane as qml
from pennylane import QubitDevice, DeviceError
from pytket.extensions.qulacs import QulacsBackend
from pytket.circuit import OpType
#from pytket.circuit import add_q_register, add_c_register
from pytket import Circuit, Qubit, Bit
from ._version import __version__

from qiskit.circuit.measure import measure
from qiskit.circuit import QuantumCircuit
#from qiskit.compiler import assemble, transpile
from qiskit.converters import circuit_to_dag, dag_to_circuit


PYTKET_OPERATION_MAP = {
    "Hadamard" : OpType.H,
    "PauliX" : OpType.X,
    "PauliY" : OpType.Y,
    "PauliZ" : OpType.Z,
    "S" : OpType.S,
    "T" : OpType.T,
    "RX" : OpType.Rx, 
    "RY" : OpType.Ry,
    "RZ" : OpType.Rz,
    "CNOT" : OpType.CX,
    "CY" : OpType.CY,
    "CZ" : OpType.CZ,
    "SWAP" : OpType.SWAP,
    "U1" : OpType.U1,
    "U2" : OpType.U2,
    "U3" : OpType.U3,
    "CRZ" : OpType.CRz,
    "Toffoli" : OpType.CCX,
    "CSWAP" : OpType.CSWAP,
    "QubitUnitary" : OpType.Unitary2qBox
}

PYTKET_OPERATION_INVERSES_MAP = {k + ".inv": v for k, v in PYTKET_OPERATION_MAP.items()}

class pytketDevice(QubitDevice):
    """MyDevice docstring"""
    name = 'pytket-pennylane plugin'
    short_name = 'pytket.mydevice'
    pennylane_requires = '>=0.13.0'
    version = '0.1.0'
    plugin_version = __version__
    author = 'KN'

    _operation_map = {**PYTKET_OPERATION_MAP, **PYTKET_OPERATION_INVERSES_MAP}
    operations = set(_operation_map.keys())
    observables = {"PauliX", "PauliY", "PauliZ"}
    _capabilities = {"model": "qubit"}

    #qml->qiskit->tket

    def __init__(self, wires, shots=1024, backend=QulacsBackend()):
        super().__init__(wires=wires, shots=shots)
        self.tket_backend = backend

    def reset(self):
        # Reset only internal data, not the options that are determined on
        # device creation
        self._circuit = Circuit(name="temp")
        self._reg  = [Qubit("q", i) for i in range(self.num_wires)]
        self._creg = [Bit("c", i) for i in range(self.num_wires)]
        for q in self._reg:
            self._circuit.add_qubit(q)
        for b in self._creg:
            self._circuit.add_bit(b)
        # self._reg = sorted(list(self._circuit.add_q_register("q", self.num_wires)))
        # self._creg = sorted(list(self._circuit.add_c_register("c", self.num_wires)))
        # print(self._reg, self._creg)
        self._state = None  # statevector of a simulator backend

    def apply(self, operations, **kwargs):
        rotations = kwargs.get("rotations", []) 

        applied_operations = self.apply_operations(operations)

        # Rotating the state for measurement in the computational basis
        rotation_circuits = self.apply_operations(rotations)
        applied_operations.extend(rotation_circuits)

        for circuit in applied_operations:
            self._circuit.append(circuit)

        if not self.tket_backend.supports_state:
            # Add measurements if they are needed
            for qr, cr in zip(self._reg, self._creg):
                self._circuit.Measure(qr, cr)

        # These operations need to run for all devices
        compiled_c = self.compile()
        self.run(compiled_c)

    def apply_operations(self, operations):
        """Apply the circuit operations.

        This method serves as an auxiliary method to :meth:`~.QiskitDevice.apply`.

        Args:
            operations (List[pennylane.Operation]): operations to be applied

        Returns:
            list[QuantumCircuit]: a list of quantum circuit objects that
                specify the corresponding operations
        """
        circuits = []

        for operation in operations:
            # Apply the circuit operations
            device_wires = self.map_wires(operation.wires)
            par = operation.parameters
            operation = operation.name

            mapped_operation = self._operation_map[operation]

            self.qubit_unitary_check(operation, par, device_wires)

            qregs = [self._reg[i] for i in device_wires.labels]

            if operation.split(".inv")[0] in ("QubitUnitary"):
                # Need to revert the order of the quantum registers used in
                # circuit such that it matches the PennyLane ordering
                qregs = list(reversed(qregs))

            ## will pytket.utils.Graph.as_nx() work here?
            ## pytket.circuit.Circuit "Encapsulates a quantum circuit using a DAG representation."?
            # dag = circuit_to_dag(QuantumCircuit(self._reg, self._creg, name=""))
            new_c = Circuit()
            for q in self._reg:
                new_c.add_qubit(q)
            for c in self._creg:
                new_c.add_bit(c)

            # gate = mapped_operation(*par)

            new_c.add_gate(mapped_operation, par, qregs)
            if operation.endswith(".inv"):
               new_c = new_c.dagger()

            ## need to apply inverse gate to dag circuit
            # dag.apply_operation_back(gate, qargs=qregs)
            # circuit = dag_to_circuit(dag)
            circuits.append(new_c)

        return circuits

    def compile(self):
        """Compile the quantum circuit to target the provided compile_backend.
        If compile_backend is None, then the target is simply the
        backend.
        """
        compile_c = self._circuit.copy()
        self.tket_backend.compile_circuit(compile_c, 2)
        return compile_c

    def run(self, compiled_c):
        """Run the compiled circuit, and query the result."""
        self._current_handle = self.tket_backend.process_circuit(compiled_c, shots=self.shots)
        result = self.tket_backend.get_result(self._current_handle)

        if self.tket_backend.supports_state:
            self._state = result.get_state(self._reg)

    @staticmethod
    def qubit_unitary_check(operation, par, wires):
        """Input check for the the QubitUnitary operation."""
        if operation == "QubitUnitary":
            if len(par[0]) != 2 ** len(wires):
                raise ValueError(
                    "Unitary matrix must be of shape (2**wires,\
                        2**wires)."
                )

    def analytic_probability(self, wires=None):
        if self._state is None:
            return None

        prob = self.marginal_prob(np.abs(self._state) ** 2, wires)
        return prob

    def generate_samples(self):

        return self.tket_backend.get_result(self._current_handle).get_shots(self._reg)
# dev = qml.device(short_name = 'pytket.mydevice', wires=2, name = 'pytket-pennylane plugin')
# @qml.qnode(dev)
# def my_quantum_function(x, y):
#     qml.RZ(x, wires=0)
#     qml.CNOT(wires=[0,1])
#     qml.RY(y, wires=1)
#     return qml.expval(qml.PauliZ(1))
