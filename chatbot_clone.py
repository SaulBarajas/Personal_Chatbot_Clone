from abc import ABC, abstractmethod
from typing import List, Dict, Union, Tuple, Optional, Any
from openai import OpenAI
import os
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import torch
from huggingface_hub import login
import json
from dotenv import load_dotenv
from collections import deque
import uuid


class LLMInterface(ABC):
    
    @abstractmethod
    def invoke(self, messages: List[Dict[str, str]]) -> str:
        pass

class Llama4bitLLM(LLMInterface):
    """
    A 4-bit quantized implementation of the Llama language model.

    This class provides an interface to the Llama model, optimized for memory efficiency
    using 4-bit quantization. It implements the LLMInterface for generating responses
    in an NPC dialogue system.

    Attributes:
        tokenizer: The tokenizer used for encoding and decoding text.
        model: The loaded and quantized Llama model.
        device: The device (CPU or CUDA) on which the model is running.

    Methods:
        execute: Generates a response given a list of message dictionaries.
    """
    def __init__(self, model_name: str = "meta-llama/Meta-Llama-3.1-8B-Instruct"):
        hf_token = os.getenv("HF_TOKEN")
        if not hf_token:
            raise ValueError("HF_TOKEN not found in environment variables")
        login(token=hf_token)
        
        # Configure 4-bit quantization
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16
        )
        
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=bnb_config,
            device_map="auto",
            #attn_implementation="flash_attention_2",
        )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
    
    def invoke(self, messages: List[Dict[str,str]]) -> str:
        """
        Generate a response using the 4-bit quantized Llama model.

        Args:
            messages (List[Dict[str,str]]): A list of message dictionaries representing the conversation history.

        Returns:
            str: The generated response from the Llama model.
        """
        # Use the model's chat template to format the input
        inputs = self.tokenizer.apply_chat_template(messages, return_tensors="pt").to(self.device)
        
        # create attention mask
        attention_mask = torch.ones_like(inputs)
        attention_mask[inputs == self.tokenizer.pad_token_id] = 0
        
        # Set pad_token_id if not already set
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token_id = self.tokenizer.eos_token_id
        
        # Generate the response
        with torch.no_grad():
            outputs = self.model.generate(
                inputs,
                attention_mask= attention_mask,
                pad_token_id=self.tokenizer.pad_token_id,
                max_new_tokens=1024, # max tokens generates
                do_sample=False, # the model uses sampling to generate tokens, which introduces randomness into the output. top_k should be 0.
                #temperature=0.7, # adjusts the randomness (lower values make it more deterministic)
                #top_p=0.95, # (nucleus sampling) limits the sampling to the most probable tokens that cumulatively add up to the set probability mass
                #top_k=0, # limits the sampling pool to only the k most likely next tokens.
                #beam_search=2, # At time step 1, besides the most likely hypothesis ("The","nice"), beam search also keeps track of the second most likely one ("The","dog"). 
                                # At time step 2, beam search finds that the word sequence ("The","dog","has"), has with 0.36 a higher probability than ("The","nice","woman"), which has 0.2
                #num_return_sequences=5, # Generates multiple sequences for beam search
                #no_repeat_ngram_size=2, # Prevents the model from repeating the same n-gram within a sequence (word sequences)
                #early_stopping=True, #so that generation is finished when all beam hypotheses reached the EOS token.
            )
        
        # Decode and return the generated response
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Extract only the assistant's response
        assistant_response = response.split("assistant\n")[-1].strip()
        
        return assistant_response
    
class llama8bLLM(LLMInterface):
    
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), 
                    base_url="https://openrouter.ai/api/v1",)
    
    def invoke(self, messages: List[Dict[str,str]]) -> str:
        completion = self.client.chat.completions.create(
            messages=messages,
            model="meta-llama/llama-3.1-8b-instruct",
            extra_body={
                "temperature": 0.0,
                "provider": {"order": ["Fireworks", "OctoAI"]},
            },
        )
        return completion.choices[0].message.content
    
class llama70bLLM(LLMInterface):
    
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), 
                    base_url="https://openrouter.ai/api/v1",)
    
    def invoke(self, messages: List[Dict[str,str]]) -> str:
        completion = self.client.chat.completions.create(
            messages=messages,
            model="meta-llama/llama-3.1-70b-instruct",
            extra_body={
                "temperature": 0.0,
                "provider": {"order": ["Hyperbolic", "Fireworks", "OctoAI"]},
            },
        )
        return completion.choices[0].message.content
    
class llama405bLLM(LLMInterface):
    
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), 
                    base_url="https://openrouter.ai/api/v1",)
    
    def invoke(self, messages: List[Dict[str,str]]) -> str:
        completion = self.client.chat.completions.create(
            messages=messages,
            model="meta-llama/llama-3.1-405b-instruct",
            extra_body={
                "temperature": 0.0,
                "provider": {"order": ["Hyperbolic", "Fireworks", "OctoAI"]},
            },
        )
        return completion.choices[0].message.content
    
    
class ConversationNode:
    def __init__(self, role: str, content: str, parent: Optional['ConversationNode'] = None, node_id: Optional[str] = None):
        self.id = node_id if node_id else str(uuid.uuid4())
        self.role = role
        self.content = content
        self.parent = parent
        self.children: List[ConversationNode] = []
        self.next_edit: Optional[ConversationNode] = None
        self.prev_edit: Optional[ConversationNode] = None

class SaveableChat:
    def __init__(self, chat_id: str, user_id: str, llm: LLMInterface):
        self.chat_id = chat_id
        self.user_id = user_id
        self.name = None
        self.system_prompt = "You are a helpful assistant."
        self.llm = llm
        self.root_node: Optional[ConversationNode] = None
        self.current_node: Optional[ConversationNode] = None
        self.recent_messages = deque(maxlen=500)
        self.running_summary = ""
        self.message_count = 0
        self.node_map: Dict[str, ConversationNode] = {}

    def add_message(self, role: str, content: str):
        new_node = ConversationNode(role, content)
        self.node_map[new_node.id] = new_node

        if self.root_node is None:
            self.root_node = new_node
            self.current_node = new_node
        else:
            leaf_node = self.get_leaf_node()
            new_node.parent = leaf_node
            leaf_node.children.append(new_node)
            self.current_node = new_node

        self.update_recent_messages_and_summary()
        self.message_count += 1

    # Helper function to find a node by its id
    def find_node(self, node_id: str) -> Optional[ConversationNode]:
        return self.node_map.get(node_id)

    def edit_message(self, node_id: str, new_content: str) -> str:
        node_to_edit = self.find_node(node_id)
        if node_to_edit is None:
            raise ValueError(f"Node not found: {node_id}")
        
        new_node = ConversationNode(node_to_edit.role, new_content, node_to_edit.parent)
        self.node_map[new_node.id] = new_node
        
        # Link the new node to the edit chain
        new_node.prev_edit = node_to_edit
        new_node.next_edit = node_to_edit.next_edit
        
        if node_to_edit.next_edit:
            node_to_edit.next_edit.prev_edit = new_node
        node_to_edit.next_edit = new_node
        
        # Update the parent's children list
        if node_to_edit.parent:
            index = node_to_edit.parent.children.index(node_to_edit)
            node_to_edit.parent.children[index] = new_node
        else:
            self.root_node = new_node
        
        # Set the new node as current
        self.current_node = new_node
        
        # Update the conversation path
        self.update_conversation_path()
        
        # Regenerate the running summary if necessary
        self.regenerate_running_summary(node_to_edit)
        
        # Regenerate the response
        conversation_up_to_edit = self.get_current_conversation()
        response = self.llm.invoke([{"role": msg["role"], "content": msg["content"]} for msg in conversation_up_to_edit])
        
        # Add the new response
        self.add_message("assistant", response)
        
        return response
    
    def regenerate_running_summary(self, edited_node: ConversationNode):
        full_conversation = self.get_current_conversation()
        
        # Condition 1: Full conversation must be greater than recent messages max
        # Condition 2: The edited message index must be less than or equal to (len(full_conversation) - recent_messages.maxlen)
        if (len(full_conversation) > self.recent_messages.maxlen and 
            full_conversation.index({"role": edited_node.role, "content": edited_node.content, "id": edited_node.id}) <= len(full_conversation) - self.recent_messages.maxlen):
            
            # Get the messages that should be summarized
            messages_to_summarize = full_conversation[:-self.recent_messages.maxlen]
            
            summary_prompt = f"""
            Please provide a concise summary of the following conversation:

            {', '.join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in messages_to_summarize])}

            Provide a concise summary that captures the main points of the conversation.
            """

            summary_messages = [
                {"role": "system", "content": "You are a helpful assistant that summarizes conversations. Make sure to keep the summary concise and relevant, while taking into account what the user and assistant have said."},
                {"role": "user", "content": summary_prompt}
            ]

            self.running_summary = self.llm.invoke(summary_messages)
        else:
            # If conditions are not met, set the running summary to an empty string
            self.running_summary = ""

        # Update recent messages
        self.recent_messages = deque(full_conversation[-self.recent_messages.maxlen:], maxlen=self.recent_messages.maxlen)

    def get_response(self) -> str:
        full_conversation = [
            {"role": "system", "content": self.system_prompt},
        ]
        
        if self.running_summary:
            full_conversation.append({"role": "system", "content": f"Previous conversation summary: {self.running_summary}"})
        
        current_conversation = self.get_current_conversation()
        full_conversation.extend([{"role": msg["role"], "content": msg["content"]} for msg in current_conversation])

        response = self.llm.invoke(full_conversation)
        self.add_message("assistant", response)
        return response
    
    def get_full_conversation_history(self) -> List[Dict[str, str]]:
        conversation = self.get_current_conversation()
        return [{"role": msg["role"], "content": msg["content"], "id": msg["id"]} for msg in conversation]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "name": self.name,
            "system_prompt": self.system_prompt,
            "running_summary": self.running_summary,
            "message_count": self.message_count,
            "root_node_id": self.root_node.id if self.root_node else None,
            "current_node_id": self.current_node.id if self.current_node else None,
            "node_map": {node_id: self.node_to_dict(node) for node_id, node in self.node_map.items()},
        }

    @staticmethod
    def node_to_dict(node: ConversationNode) -> Dict[str, Any]:
        return {
            "id": node.id,
            "role": node.role,
            "content": node.content,
            "parent_id": node.parent.id if node.parent else None,
            "children_ids": [child.id for child in node.children],
            "prev_edit_id": node.prev_edit.id if node.prev_edit else None,
            "next_edit_id": node.next_edit.id if node.next_edit else None,
        }

    def save(self, directory: str = "saved_chats"):
        os.makedirs(directory, exist_ok=True)
        filename = f"{self.user_id}_{self.chat_id}.json"
        with open(os.path.join(directory, filename), "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], llm: LLMInterface) -> 'SaveableChat':
        chat = cls(data["chat_id"], data["user_id"], llm)
        chat.name = data["name"]
        chat.system_prompt = data["system_prompt"]
        chat.running_summary = data["running_summary"]
        chat.message_count = data["message_count"]

        # Reconstruct node_map
        chat.node_map = {}
        for node_id, node_data in data["node_map"].items():
            chat.node_map[node_id] = ConversationNode(
                role=node_data["role"],
                content=node_data["content"],
                node_id=node_data["id"]
            )

        # Set up node relationships
        for node_id, node_data in data["node_map"].items():
            node = chat.node_map[node_id]
            if node_data["parent_id"]:
                node.parent = chat.node_map[node_data["parent_id"]]
            node.children = [chat.node_map[child_id] for child_id in node_data["children_ids"]]
            if node_data["prev_edit_id"]:
                node.prev_edit = chat.node_map[node_data["prev_edit_id"]]
            if node_data["next_edit_id"]:
                node.next_edit = chat.node_map[node_data["next_edit_id"]]

        chat.root_node = chat.node_map[data["root_node_id"]] if data["root_node_id"] else None
        chat.current_node = chat.node_map[data["current_node_id"]] if data["current_node_id"] else None

        # Populate recent_messages
        current_conversation = chat.get_current_conversation()
        chat.recent_messages = deque(current_conversation[-chat.recent_messages.maxlen:], maxlen=chat.recent_messages.maxlen)

        return chat

    @classmethod
    def load(cls, chat_id: str, user_id: str, llm: LLMInterface, directory: str = "saved_chats"):
        filename = f"{user_id}_{chat_id}.json"
        filepath = os.path.join(directory, filename)
        if not os.path.exists(filepath):
            return cls(chat_id, user_id, llm)
        
        with open(filepath, "r") as f:
            data = json.load(f)
        
        return cls.from_dict(data, llm)

    def generate_name(self, user_input: str) -> str:
        name_prompt = f"""
        Please generate a name for a chat that starts with this message: '{user_input}'
        
        Your response should only be the name of the chat, nothing else.
        
        For example:
        User input: "Hello, how are you?"
        Chat name: "Greeting"
        
        User input: "I need help with my resume"
        Chat name: "Resume Help"
        
        User input: "How can I improve my cover letter?"
        Chat name: "Cover Letter Help"
        
        User input: "What are the best interview questions to ask?"
        Chat name: "Asking Interview Questions"
        
        User input: "How do you code a chatbot?"
        Chat name: "Coding a Chatbot"
        
        """
        naming_prompt = [{"role": "system", "content": "You are a chat naming assistant. Your task is to create a short, relevant name for a chat based on the user's first message. The name should be concise and descriptive."},
                         {"role": "user", "content": name_prompt}]
        self.name = self.llm.invoke(naming_prompt).strip()
        return self.name
    
    def switch_to_edit(self, node_id: str):
        node = self.find_node(node_id)
        if node:
            self.current_node = node
            # Update the conversation path
            self.update_conversation_path()
            self.update_recent_messages_and_summary()
        else:
            raise ValueError(f"Node not found: {node_id}")

    # Helper function to update the conversation path
    def update_conversation_path(self):
        if not self.current_node:
            return

        path = []
        current = self.current_node
        while current:
            path.append(current)
            current = current.parent

        path.reverse()

        # Update the children links
        for i in range(len(path) - 1):
            parent = path[i]
            child = path[i + 1]
            
            # Find the earliest edit of the child that has this parent
            earliest_child = child
            while earliest_child.prev_edit and earliest_child.prev_edit.parent == parent:
                earliest_child = earliest_child.prev_edit
            
            # Update parent's children list if necessary
            if earliest_child not in parent.children:
                parent.children = [c for c in parent.children if c.id != earliest_child.id] + [earliest_child]

            # Update the parent of all subsequent edits
            current_edit = earliest_child
            while current_edit:
                current_edit.parent = parent
                current_edit = current_edit.next_edit

        self.root_node = path[0]

        # Ensure the current_node is part of the main path
        current_edit = self.current_node
        while current_edit.prev_edit and current_edit.prev_edit.parent == current_edit.parent:
            current_edit = current_edit.prev_edit
        
        if current_edit.parent:
            index = current_edit.parent.children.index(current_edit)
            current_edit.parent.children[index] = self.current_node

        # Update children of the current node
        if self.current_node.children:
            child = self.current_node.children[0]
            while child.prev_edit and child.prev_edit.parent == self.current_node:
                child = child.prev_edit
            self.current_node.children = [child]

    def update_recent_messages_and_summary(self):
        conversation = self.get_current_conversation()
        self.recent_messages = deque(conversation[-self.recent_messages.maxlen:], maxlen=self.recent_messages.maxlen)
        
        if len(conversation) > self.recent_messages.maxlen:
            dropped_messages = conversation[:-self.recent_messages.maxlen]
            self.update_running_summary(dropped_messages)

    # Helper function to update the running summary
    def update_running_summary(self, dropped_messages: List[Dict[str, str]]):
        summary_prompt = f"""
        Please update the following summary with the new information:

        Current summary: {self.running_summary}

        Dropped messages to be summarized:
        {', '.join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in dropped_messages])}

        Provide a concise updated summary.
        """

        summary_messages = [
            {"role": "system", "content": "You are a helpful assistant that updates conversation summaries. Make sure to keep the summary concise and relevant, while taking into account what the user and assistant have said."},
            {"role": "user", "content": summary_prompt}
        ]

        self.running_summary = self.llm.invoke(summary_messages)
        
    # Helper function to get the current conversation
    def get_current_conversation(self) -> List[Dict[str, Any]]:
        conversation = []
        node = self.current_node
        
        if node is None:
            return conversation  # Return an empty list if there are no messages yet
        
        # Traverse up to collect all parent nodes
        while node:
            edits = self.get_node_edits(node.id)
            current_edit_index = next((i for i, edit in enumerate(edits) if edit.id == node.id), 0)
            conversation.insert(0, {
                "role": node.role,
                "content": node.content,
                "id": node.id,
                "edits": [{"id": edit.id, "role": edit.role, "content": edit.content} for edit in edits],
                "current_edit_index": current_edit_index
            })
            # Move to the parent of the leftmost edit
            while node.prev_edit:
                node = node.prev_edit
            node = node.parent

        # Now, traverse down from the current node to include all children
        node = self.current_node
        while node and node.children:
            child = node.children[0]  # Always choose the first child
            edits = self.get_node_edits(child.id)
            current_edit_index = next((i for i, edit in enumerate(edits) if edit.id == child.id), 0)
            conversation.append({
                "role": child.role,
                "content": child.content,
                "id": child.id,
                "edits": [{"id": edit.id, "role": edit.role, "content": edit.content} for edit in edits],
                "current_edit_index": current_edit_index
            })
            node = child

        return conversation

    # Helper function to get the edits of a node
    def get_node_edits(self, node_id: str) -> List[ConversationNode]:
        node = self.find_node(node_id)
        if not node:
            return []
        
        edits = [node]
        
        # Traverse left
        current = node.prev_edit
        while current:
            edits.insert(0, current)
            current = current.prev_edit
        
        # Traverse right
        current = node.next_edit
        while current:
            edits.append(current)
            current = current.next_edit
        
        return edits

    def get_leaf_node(self) -> ConversationNode:
        if self.current_node is None:
            return self.root_node
        
        node = self.current_node
        while node.children:
            node = node.children[0]
        return node

class Chatbot:
    def __init__(self, llm: LLMInterface, user_id: str):
        self.llm = llm
        self.user_id = user_id
        self.chats = {}
        self.load_user_chats()

    # creates a new chat or loads an existing one
    # TODO: Add to API
    def create_chat(self, chat_id: str, user_id: str) -> SaveableChat:
        key = f"{user_id}_{chat_id}"
        if key not in self.chats:
            self.chats[key] = SaveableChat(chat_id, user_id, self.llm)
        return self.chats[key]

    # gets a chat by chat_id and user_id and returns it. Adds it to chats dictionary if it doesn't exist
    def get_chat(self, chat_id: str, user_id: str) -> SaveableChat:
        key = f"{user_id}_{chat_id}"
        if key not in self.chats:
            self.chats[key] = SaveableChat.load(chat_id, user_id, self.llm)
        return self.chats[key]
    
    # loads all chats for a user
    def load_user_chats(self, directory: str = "saved_chats") -> List[SaveableChat]:
        user_chats = []
        if os.path.exists(directory):
            for filename in os.listdir(directory):
                if filename.startswith(f"{self.user_id}_") and filename.endswith(".json"):
                    chat_id = filename[len(self.user_id)+1:-5]  # Remove user_id_ prefix and .json suffix
                    chat = self.get_chat(chat_id, self.user_id)
                    user_chats.append(chat)
        return user_chats
    
    # gets a summary of all chats for a user
    # TODO: Add to API
    def get_user_chat_summaries(self) -> List[Dict[str, Union[str, int, List[Dict[str, str]]]]]:
        chats = self.load_user_chats()
        summaries = []
        for chat in chats:
            full_history = chat.get_full_conversation_history()
            summaries.append({
                "chat_id": chat.chat_id,
                "name": chat.name,
                "last_message": full_history[-1]["content"] if full_history else "",
                "full_history": full_history,
                "message_count": chat.message_count,
                "recent_messages": list(chat.recent_messages),
                "running_summary": chat.running_summary
            })
        return summaries

    # sets the system prompt for a chat
    # TODO: Add to API
    def set_system_prompt(self, user_id: str, chat_id: str, prompt: str):
        chat = self.get_chat(chat_id, user_id)
        chat.set_system_prompt(prompt)
        chat.save()  # Save the chat after updating the system prompt
        
    def set_name(self, user_id: str, chat_id: str, name: str):
        chat = self.get_chat(chat_id, user_id)
        chat.set_name(name)
        chat.save()
        
    def set_llm(self, llm: LLMInterface):
        self.llm = llm
        # Update the LLM for all existing chats
        for chat in self.chats.values():
            chat.llm = llm

    # chats with the user
    # TODO: Add to API
    def chat(self, chat_id: str, user_id: str, user_input: str) -> str:
        chat = self.get_chat(chat_id, user_id)
        if not chat.get_full_conversation_history():
            chat.generate_name(user_input)
        chat.add_message("user", user_input)
        response = chat.get_response()
        chat.save()
        return response

    def edit_message(self, chat_id: str, user_id: str, node_id: str, new_content: str) -> str:
        chat = self.get_chat(chat_id, user_id)
        response = chat.edit_message(node_id, new_content)
        chat.save()
        return response

    def save_chat(self, chat_id: str, user_id: str):
        chat = self.get_chat(chat_id, user_id)
        chat.save()

# TODO: Add editting of messages 
# (Thought for this would be to implement a tree structure of message index and versions in order to allow for multiple edits of the same message index and also allow them to keep different conversation instances.)
# (This allows the user to look at a previous version of an edit the tree is to be able to keep track of different conversation instances with potentially different children edits.
# TODO: Multi-user support: Implement a user management system to handle multiple users with authentication.
# DONE: Chat summarization: Add a feature to generate summaries of long conversations.
# TODO: Voice input/output: Add support for voice messages or text-to-speech for responses.
# TODO: Image generation: Integrate an image generation model to create images based on text prompts.
# TODO: Context-aware responses: Implement a feature to maintain longer-term context across multiple chat sessions.
# TODO: Integration with external APIs: Add the ability to fetch real-time data (e.g., weather, news) to enhance responses.
# TODO:  File attachment support: Allow users to attach and share files within the chat.
    
if __name__ == "__main__":
    load_dotenv()
    llm = llama8bLLM()
    chatbot = Chatbot(llm, "saulb423")
    chatbot.create_chat(user_id="saulb423",  chat_id="1")
    chatbot.chat(user_id="saulb423", chat_id="1", user_input="Hey can you help me prepare a sales pitch for a job interview?")
    print(chatbot.get_user_chat_summaries())
    print(len(chatbot.get_chat(chat_id="1", user_id="saulb423").get_full_history()))
    print(len(chatbot.get_chat(chat_id="1", user_id="saulb423").recent_messages))